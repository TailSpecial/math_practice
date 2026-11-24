from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q, Count
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .documents import variant_document
from .forms import AllocationForm, AssignmentTemplateForm, BulkAllocationForm, CohortForm, ImportForm, MaterialForm, ReportForm, ReviewForm, StudentAddForm, TaskForm, UniversityAccountForm
from .models import AssignmentTemplate, Cohort, Enrollment, Material, Profile, Report, Task, Topic
from .services import add_student, generate_variants, generation_readiness, import_students, provision_account


class PortalLoginView(auth_views.LoginView):
    template_name = 'login.html'
    redirect_authenticated_user = True
    def post(self, request, *args, **kwargs):
        self.rate_key = 'login:' + request.META.get('REMOTE_ADDR', '') + ':' + request.POST.get('username', '')[:150]
        if cache.get(self.rate_key, 0) >= 10:
            messages.error(request, 'Слишком много попыток входа. Повторите через 10 минут.')
            return redirect('login')
        return super().post(request, *args, **kwargs)
    def form_invalid(self, form):
        cache.set(self.rate_key, cache.get(self.rate_key, 0) + 1, 600)
        return super().form_invalid(form)
    def form_valid(self, form):
        cache.delete(self.rate_key)
        return super().form_valid(form)


def role_required(*roles):
    def decorate(fn):
        @login_required
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if not profile or not profile.department or (roles and profile.role not in roles):
                raise PermissionDenied
            request.profile = profile
            return fn(request, *args, **kwargs)
        return wrapped
    return decorate


def accessible_enrollments(profile):
    qs = Enrollment.objects.select_related('student__user', 'supervisor', 'cohort__program', 'variant')
    if profile.role == Profile.Role.STUDENT:
        return qs.filter(student=profile)
    if profile.role == Profile.Role.TEACHER:
        return qs.filter(supervisor=profile, department=profile.department)
    if profile.role == Profile.Role.HEAD:
        return qs.filter(department=profile.department, cohort__department=profile.department)
    return qs.none()


@role_required()
def dashboard(request):
    enrollments = accessible_enrollments(request.profile)
    years = list(enrollments.values_list('cohort__academic_year', flat=True).distinct().order_by('-cohort__academic_year'))
    year = request.GET.get('year', str(years[0]) if years else '')
    if year.isdigit():
        enrollments = enrollments.filter(cohort__academic_year=int(year))
    query = request.GET.get('q', '').strip()
    if query:
        enrollments = enrollments.filter(Q(student__full_name__unicode_contains=query) | Q(cohort__name__unicode_contains=query))
    reports = Report.objects.filter(enrollment__in=enrollments)
    data = {'enrollments': enrollments, 'years': years, 'selected_year': year, 'query': query,
            'total': enrollments.count(), 'generated': enrollments.filter(variant__isnull=False).count(),
            'pending': reports.filter(status=Report.Status.SUBMITTED).count(), 'accepted': reports.filter(status=Report.Status.ACCEPTED).values('enrollment').distinct().count(),
            'recent_reports': reports.select_related('enrollment__student')[:5]}
    if request.profile.role == Profile.Role.STUDENT:
        data['enrollment'] = enrollments.first()
        return render(request, 'student_dashboard.html', data)
    return render(request, 'dashboard.html', data)


@role_required()
def enrollment_detail(request, pk):
    enrollment = get_object_or_404(accessible_enrollments(request.profile), pk=pk)
    latest = enrollment.reports.first()
    form = ReportForm()
    if request.method == 'POST':
        if request.profile.role != Profile.Role.STUDENT or enrollment.student != request.profile:
            raise PermissionDenied
        form = ReportForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                Enrollment.objects.select_for_update().get(pk=enrollment.pk)
                latest = enrollment.reports.first()
                if not hasattr(enrollment, 'variant'):
                    form.add_error(None, 'Дождитесь выдачи индивидуального задания.')
                elif latest and latest.status in (Report.Status.ACCEPTED, Report.Status.SUBMITTED):
                    form.add_error(None, 'Дождитесь проверки отчёта. Новая загрузка доступна после возврата на доработку.')
                else:
                    file = form.cleaned_data['file']
                    Report.objects.create(enrollment=enrollment, file=file, original_name=Path(file.name).name[:250])
                    messages.success(request, 'Отчёт загружен и отправлен преподавателю.')
                    return redirect('enrollment', pk=pk)
    return render(request, 'enrollment.html', {'enrollment': enrollment, 'reports': enrollment.reports.all(), 'latest': latest, 'form': form, 'allocation_form': AllocationForm(instance=enrollment, department=request.profile.department) if request.profile.role == Profile.Role.HEAD else None})


@role_required('head')
@require_POST
def allocate(request, pk):
    with transaction.atomic():
        enrollment = get_object_or_404(accessible_enrollments(request.profile).select_for_update(of=('self',)), pk=pk)
        form = AllocationForm(request.POST, instance=enrollment, department=request.profile.department)
        if form.is_valid():
            form.save()
            messages.success(request, 'Руководитель назначен. Выданный вариант сохранён; новый преподаватель получил доступ к нему и отчётам.')
        else:
            messages.error(request, 'Выберите преподавателя своей кафедры.')
    return redirect('enrollment', pk=pk)


@role_required()
def download_variant(request, pk, kind):
    enrollment = get_object_or_404(accessible_enrollments(request.profile), pk=pk, variant__isnull=False)
    if kind not in ('assignment', 'report'):
        raise PermissionDenied
    return FileResponse(variant_document(enrollment.variant, full=kind == 'report'), as_attachment=True, filename=f'{kind}-{enrollment.variant.pk:04d}.docx')


@role_required()
def download_report(request, pk):
    report = get_object_or_404(Report.objects.filter(enrollment__in=accessible_enrollments(request.profile)), pk=pk)
    return FileResponse(report.file.open('rb'), as_attachment=True, filename=report.original_name)


@role_required('teacher')
def review_report(request, pk):
    report = get_object_or_404(Report.objects.filter(enrollment__in=accessible_enrollments(request.profile)), pk=pk)
    form = ReviewForm(request.POST or None, instance=report)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            locked_enrollment = Enrollment.objects.select_for_update().get(pk=report.enrollment_id)
            if locked_enrollment.supervisor_id != request.profile.pk or locked_enrollment.department != request.profile.department:
                raise PermissionDenied
            if report.enrollment.reports.first().pk != report.pk:
                form.add_error(None, 'Это предыдущая версия отчёта. Откройте актуальную загрузку.')
            else:
                result = form.save(commit=False)
                result.reviewed_by = request.profile
                result.reviewed_at = timezone.now()
                result.save()
                messages.success(request, 'Результат проверки сохранён.')
                return redirect('enrollment', pk=report.enrollment_id)
    return render(request, 'form.html', {'form': form, 'title': 'Проверка отчёта', 'subtitle': str(report.enrollment.student), 'back_url': f'/students/{report.enrollment_id}/', 'submit_label': 'Сохранить результат', 'report': report})


@role_required('teacher', 'head')
def groups(request):
    qs = Cohort.objects.filter(department=request.profile.department).select_related('program').prefetch_related('topics')
    if request.profile.role == Profile.Role.TEACHER:
        qs = qs.filter(enrollments__supervisor=request.profile).distinct()
    return render(request, 'groups.html', {'groups': qs.order_by('-academic_year', 'name')})


@role_required('head')
def group_create(request):
    form = CohortForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        group = form.save(commit=False)
        group.department = request.profile.department
        group.save()
        form.save_m2m()
        messages.success(request, 'Группа создана. Импортируйте список студентов.')
        return redirect('group', pk=group.pk)
    return render(request, 'form.html', {'form': form, 'title': 'Новая группа', 'subtitle': 'Направление, курс, сроки и темы практики', 'back_url': '/groups/'})


@role_required('head')
def group_edit(request, pk):
    group = get_object_or_404(Cohort, pk=pk, department=request.profile.department)
    form = CohortForm(request.POST or None, instance=group)
    if request.method == 'POST':
        with transaction.atomic():
            locked_group = Cohort.objects.select_for_update().get(pk=group.pk)
            form = CohortForm(request.POST, instance=locked_group)
            if form.is_valid():
                form.save()
                messages.success(request, 'Параметры группы сохранены. Ранее выданные документы и задания не изменились.')
                return redirect('group', pk=pk)
    return render(request, 'form.html', {'form': form, 'title': f'Параметры группы {group.name}', 'subtitle': 'Изменения применяются к новым вариантам. Уже выданные варианты сохраняют исходные данные.', 'back_url': f'/groups/{pk}/'})


@role_required('head')
def student_add(request, pk):
    group = get_object_or_404(Cohort, pk=pk, department=request.profile.department)
    form = StudentAddForm(request.POST or None, department=request.profile.department)
    if request.method == 'POST' and form.is_valid():
        try:
            enrollment, created = add_student(group, form.cleaned_data['username'], form.cleaned_data['full_name'], form.cleaned_data['supervisor'])
            messages.success(request, 'Студент добавлен и назначен руководителю.' if created else 'Студент уже есть в группе. Его задание сохранено.')
            return redirect('enrollment', pk=enrollment.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, 'Аккаунт с таким логином уже создаётся. Обновите страницу и повторите.')
    return render(request, 'form.html', {'form': form, 'title': 'Добавить студента', 'subtitle': f'{group.name} · {group.program}', 'back_url': f'/groups/{pk}/'})


@role_required('head')
def teachers(request):
    people = Profile.objects.filter(role=Profile.Role.TEACHER, department=request.profile.department).select_related('user').annotate(student_count=Count('supervised')).order_by('full_name')
    return render(request, 'teachers.html', {'teachers': people})


@role_required('head')
def teacher_add(request):
    form = UniversityAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            provision_account(form.cleaned_data['username'], form.cleaned_data['full_name'], Profile.Role.TEACHER, request.profile.department)
            messages.success(request, 'Преподаватель добавлен. Теперь ему можно назначать студентов.')
            return redirect('teachers')
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, 'Логин уже занят. Обновите страницу и повторите.')
    return render(request, 'form.html', {'form': form, 'title': 'Добавить преподавателя', 'subtitle': request.profile.department, 'back_url': '/teachers/'})


@role_required('head')
@require_POST
def bulk_allocate(request, pk):
    group = get_object_or_404(Cohort, pk=pk, department=request.profile.department)
    form = BulkAllocationForm(request.POST, cohort=group)
    if form.is_valid():
        with transaction.atomic():
            rows = list(form.cleaned_data['students'].select_for_update())
            Enrollment.objects.filter(pk__in=[row.pk for row in rows], cohort=group, department=request.profile.department).update(supervisor=form.cleaned_data['supervisor'])
        messages.success(request, f'Руководитель назначен студентам: {len(rows)}. Задания и отчёты сохранены.')
    else:
        messages.error(request, ' '.join(error for errors in form.errors.values() for error in errors))
    return redirect('group', pk=pk)


@role_required('teacher', 'head')
def group_detail(request, pk):
    group = get_object_or_404(Cohort, pk=pk, department=request.profile.department)
    enrollments = accessible_enrollments(request.profile).filter(cohort=group)
    if request.profile.role == Profile.Role.TEACHER and not enrollments.exists():
        raise PermissionDenied
    form = ImportForm()
    if request.method == 'POST':
        if request.profile.role != Profile.Role.HEAD:
            raise PermissionDenied
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                count = import_students(group, form.cleaned_data['file'])
                messages.success(request, f'Добавлено студентов: {count}. Ранее загруженные записи сохранены.')
                return redirect('group', pk=pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    data = {'group': group, 'enrollments': enrollments, 'form': form}
    if request.profile.role == Profile.Role.HEAD:
        data.update({'bulk_form': BulkAllocationForm(cohort=group), 'selectable': True})
    else:
        data['readiness'] = generation_readiness(group, request.profile)
    return render(request, 'group.html', data)


@role_required('teacher')
@require_POST
def generate(request, pk):
    group = get_object_or_404(Cohort.objects.filter(department=request.profile.department, enrollments__supervisor=request.profile).distinct(), pk=pk)
    try:
        count = generate_variants(group.pk, request.profile)
        messages.success(request, f'Сформировано вариантов: {count}. Ранее выданные задания сохранены.')
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    except IntegrityError:
        messages.error(request, 'Другой преподаватель уже занял часть задач. Повторите формирование.')
    except OperationalError as exc:
        if 'locked' not in str(exc).lower():
            raise
        messages.error(request, 'Другой пользователь обновляет данные. Подождите несколько секунд и повторите формирование.')
    return redirect('group', pk=pk)


@role_required('head')
def csv_template(request):
    content = 'student_login;student_name;supervisor_login;supervisor_name;department\nstudent.login;Иванов Иван Иванович;teacher.login;Петров Пётр Петрович;' + request.profile.department + '\n'
    response = HttpResponse('\ufeff' + content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="students-template.csv"'
    return response


@role_required('teacher', 'head')
def task_bank(request):
    tasks = Task.objects.filter(Q(department=request.profile.department) | Q(department='')).select_related('topic').order_by('topic__name', 'id')
    topic = request.GET.get('topic', '')
    query = request.GET.get('q', '').strip()
    if topic.isdigit():
        tasks = tasks.filter(topic_id=topic)
    if query:
        tasks = tasks.filter(text__unicode_contains=query)
    from django.core.paginator import Paginator
    page = Paginator(tasks, 20).get_page(request.GET.get('page'))
    return render(request, 'bank.html', {'page': page, 'topics': Topic.objects.all(), 'selected_topic': topic, 'query': query, 'task_count': tasks.count()})


@role_required('head')
def task_edit(request, pk=None):
    task = get_object_or_404(Task, pk=pk, department=request.profile.department) if pk else None
    form = TaskForm(request.POST or None, instance=task)
    if request.method == 'POST' and form.is_valid():
        task = form.save(commit=False)
        task.department = request.profile.department
        task.save()
        form.save_m2m()
        messages.success(request, 'Задача сохранена. Уже выданные варианты не изменились.')
        return redirect('bank')
    return render(request, 'form.html', {'form': form, 'title': 'Изменить задачу' if pk else 'Добавить задачу', 'back_url': '/bank/'})


@role_required('head')
def assignment_template(request):
    instance, _ = AssignmentTemplate.objects.get_or_create(department=request.profile.department)
    form = AssignmentTemplateForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Бланк сохранён. Он применяется к новым вариантам; ранее выданные документы сохраняются.')
        return redirect('assignment_template')
    return render(request, 'form.html', {'form': form, 'title': 'Бланк индивидуального задания', 'subtitle': 'Содержание бланка для вашей кафедры. Данные студента, руководитель, сроки и задачи подставляются автоматически.', 'back_url': '/', 'submit_label': 'Сохранить бланк'})


@role_required()
def materials(request):
    return render(request, 'materials.html', {'materials': Material.objects.select_related('topic').order_by('-created_at')})


@role_required('head')
def material_create(request):
    form = MaterialForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Материал добавлен в библиотеку.')
        return redirect('materials')
    return render(request, 'form.html', {'form': form, 'title': 'Добавить материал', 'back_url': '/materials/'})


@role_required()
def material_download(request, pk):
    material = get_object_or_404(Material, pk=pk)
    if not material.file:
        raise PermissionDenied
    return FileResponse(material.file.open('rb'), as_attachment=True, filename=Path(material.file.name).name)
