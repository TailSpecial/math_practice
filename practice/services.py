import csv
import io
import secrets
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import AssignmentTemplate, Cohort, Enrollment, Profile, Task, Variant, VariantItem
from django.db.models import Q


def eligible_tasks(cohort, topic):
    candidates = Task.objects.filter(topic=topic, active=True).filter(
        Q(programs=cohort.program) | Q(programs__isnull=True)
    ).filter(Q(department=cohort.department) | Q(department='')).distinct()
    return [task for task in candidates if str(cohort.course) in task.courses.split(',')]


def generation_readiness(cohort, teacher):
    pending = cohort.enrollments.filter(supervisor=teacher, variant__isnull=True).count()
    used = set(VariantItem.objects.filter(academic_year=cohort.academic_year).values_list('task_id', flat=True))
    rows = []
    for topic in cohort.topics.all():
        tasks = eligible_tasks(cohort, topic)
        available = sum(task.pk not in used for task in tasks)
        rows.append({'topic': topic, 'total': len(tasks), 'available': available,
                     'ready': len(tasks) >= 25 and available >= pending})
    return {'pending': pending, 'topics': rows, 'ready': bool(rows) and pending > 0 and all(row['ready'] for row in rows)}


@transaction.atomic
def provision_account(username, full_name, role, department):
    if role not in (Profile.Role.STUDENT, Profile.Role.TEACHER) or not department:
        raise ValidationError('Разрешено добавлять только студентов и преподавателей своей кафедры.')
    user = User.objects.filter(username=username).first()
    if user:
        profile = Profile.objects.filter(user=user).first()
        if not profile or profile.role != role or profile.department != department:
            raise ValidationError('Этот логин занят пользователем с другой ролью или кафедрой.')
        if profile.full_name != full_name:
            raise ValidationError('ФИО не совпадает с существующей записью этого пользователя.')
        return profile
    user = User(username=username)
    user.set_unusable_password()
    user.full_clean()
    user.save()
    profile = Profile(user=user, full_name=full_name, role=role, department=department)
    profile.full_clean()
    profile.save()
    return profile


@transaction.atomic
def add_student(cohort, username, full_name, supervisor):
    cohort = Cohort.objects.select_for_update().get(pk=cohort.pk)
    if supervisor.role != Profile.Role.TEACHER or supervisor.department != cohort.department or not supervisor.user.is_active:
        raise ValidationError('Выберите активного преподавателя своей кафедры.')
    student = provision_account(username, full_name, Profile.Role.STUDENT, cohort.department)
    if student.enrollments.filter(cohort__academic_year=cohort.academic_year).exclude(cohort=cohort).exists():
        raise ValidationError('Студент уже включён в другую группу этого учебного года.')
    enrollment, created = Enrollment.objects.get_or_create(cohort=cohort, student=student, defaults={'supervisor': supervisor, 'department': cohort.department})
    if not created and enrollment.supervisor_id != supervisor.pk:
        raise ValidationError('Студент уже добавлен. Для смены руководителя используйте распределение.')
    return enrollment, created


@transaction.atomic
def generate_variants(cohort_id, teacher):
    cohort = Cohort.objects.select_for_update().get(pk=cohort_id)
    if teacher.role != Profile.Role.TEACHER or not teacher.department or cohort.department != teacher.department:
        raise ValidationError('Формировать задания может только преподаватель своей кафедры.')
    topics = list(cohort.topics.all())
    if not topics:
        raise ValidationError('Выберите хотя бы одну тему для группы.')
    students = list(cohort.enrollments.select_for_update(of=('self',)).filter(variant__isnull=True, supervisor=teacher).select_related('student', 'supervisor'))
    if not students:
        return 0
    pools = {}
    for topic in topics:
        eligible = eligible_tasks(cohort, topic)
        if len(eligible) < 25:
            raise ValidationError(f'Тема «{topic.name}»: нужно не менее 25 подходящих задач, сейчас {len(eligible)}.')
        used = set(VariantItem.objects.filter(academic_year=cohort.academic_year).values_list('task_id', flat=True))
        available = [t for t in eligible if t.pk not in used]
        if len(available) < len(students):
            raise ValidationError(f'Тема «{topic.name}»: свободных задач {len(available)}, студентов без варианта {len(students)}. Пополните банк. Уже выданные варианты сохранены.')
        secrets.SystemRandom().shuffle(available)
        pools[topic.pk] = available
    template = AssignmentTemplate.objects.filter(department=cohort.department).first()
    for index, enrollment in enumerate(students):
        variant = Variant.objects.create(enrollment=enrollment, metadata={
            'student': enrollment.student.full_name, 'supervisor': enrollment.supervisor.full_name,
            'department': enrollment.department, 'program': str(cohort.program),
            'competencies': cohort.program.competencies, 'practice_title': cohort.practice_title,
            'start_date': cohort.start_date.isoformat(), 'end_date': cohort.end_date.isoformat(),
            'cohort': cohort.name, 'academic_year': cohort.academic_year,
            'heading': template.heading if template else 'Индивидуальное задание',
            'introduction': template.introduction if template else '',
            'footer': template.footer if template else '',
        })
        for topic in topics:
            task = pools[topic.pk][index]
            VariantItem.objects.create(variant=variant, task=task, academic_year=cohort.academic_year, topic_name=topic.name, text=task.text)
    return len(students)


@transaction.atomic
def import_students(cohort, uploaded):
    try:
        content = uploaded.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValidationError('Сохраните CSV в кодировке UTF-8.')
    if not content.strip():
        raise ValidationError('CSV пуст.')
    delimiter = ';' if ';' in content.splitlines()[0] else ','
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter, strict=True)
    required = {'student_login', 'student_name', 'supervisor_login', 'supervisor_name', 'department'}
    try:
        if not required.issubset(reader.fieldnames or []):
            raise ValidationError('Нужны столбцы: ' + ', '.join(sorted(required)))
        rows = list(reader)
    except csv.Error:
        raise ValidationError('Не удалось прочитать CSV. Проверьте кавычки, разделители и длину полей.')
    added = 0
    if not rows:
        raise ValidationError('В CSV нет студентов.')
    for number, row in enumerate(rows, 2):
        row = {k: (v or '').strip() for k, v in row.items() if k}
        if not all(row.get(k) for k in required):
            raise ValidationError(f'Строка {number}: заполните все обязательные поля.')
        if row['department'] != cohort.department:
            raise ValidationError(f'Строка {number}: кафедра должна совпадать с кафедрой группы ({cohort.department}).')
        profiles = []
        for prefix, role in [('student', Profile.Role.STUDENT), ('supervisor', Profile.Role.TEACHER)]:
            username = row[f'{prefix}_login']
            if len(username) > 150 or len(row[f'{prefix}_name']) > 250 or len(row['department']) > 200:
                raise ValidationError(f'Строка {number}: превышена допустимая длина поля.')
            try:
                profile = provision_account(username, row[f'{prefix}_name'], role, row['department'])
            except ValidationError as exc:
                raise ValidationError(f'Строка {number}: ' + ' '.join(exc.messages))
            profiles.append(profile)
        student, supervisor = profiles
        if student.enrollments.filter(cohort__academic_year=cohort.academic_year).exclude(cohort=cohort).exists():
            raise ValidationError(f'Строка {number}: студент уже включён в другую группу этого учебного года.')
        enrollment, created = Enrollment.objects.get_or_create(cohort=cohort, student=student, defaults={'supervisor': supervisor, 'department': row['department']})
        if not created and (enrollment.supervisor != supervisor or enrollment.department != row['department']):
            raise ValidationError(f'Строка {number}: назначение уже существует с другим руководителем или кафедрой. Измените его в панели управления.')
        added += int(created)
    return added
