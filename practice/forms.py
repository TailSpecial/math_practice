import zipfile
from pathlib import Path
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import AssignmentTemplate, Cohort, Enrollment, Material, Profile, Report, Task


class CohortForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.enrollments.exists():
            self.fields['academic_year'].disabled = True
            self.fields['academic_year'].help_text = 'У группы со студентами год закреплён. Для нового года создайте другую группу.'
    class Meta:
        model = Cohort
        fields = ['name', 'program', 'course', 'academic_year', 'start_date', 'end_date', 'practice_title', 'topics']
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), 'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), 'topics': forms.CheckboxSelectMultiple()}
    def clean(self):
        data = super().clean()
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', 'Конец практики должен быть после начала.')
        return data


class ImportForm(forms.Form):
    file = forms.FileField(label='CSV со списком студентов', help_text='UTF-8, разделитель ; или запятая. Максимум 2 МБ.')
    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 2 * 1024 * 1024:
            raise ValidationError('Максимальный размер CSV — 2 МБ.')
        return file


class ReportForm(forms.Form):
    file = forms.FileField(label='Отчёт по практике', help_text='PDF или DOCX, до 20 МБ')
    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 20 * 1024 * 1024:
            raise ValidationError('Максимальный размер отчёта — 20 МБ.')
        ext = Path(file.name).suffix.lower()
        valid = False
        if ext == '.pdf':
            valid = file.read(5) == b'%PDF-'
        elif ext == '.docx':
            try:
                with zipfile.ZipFile(file) as archive:
                    valid = 'word/document.xml' in archive.namelist() and '[Content_Types].xml' in archive.namelist()
            except (zipfile.BadZipFile, OSError):
                pass
        file.seek(0)
        if not valid:
            raise ValidationError('Выберите корректный PDF или документ Word (.docx).')
        return file


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ['status', 'grade', 'comment']
        labels = {'status': 'Результат проверки'}
        widgets = {'comment': forms.Textarea(attrs={'rows': 4})}
    def clean(self):
        data = super().clean()
        if data.get('status') == Report.Status.REVISION and not data.get('comment'):
            self.add_error('comment', 'Укажите, что нужно исправить.')
        if data.get('status') == Report.Status.ACCEPTED and not data.get('grade'):
            self.add_error('grade', 'Укажите оценку принятого отчёта.')
        if data.get('status') != Report.Status.ACCEPTED:
            data['grade'] = None
        return data


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ['title', 'topic', 'description', 'file', 'url']
    def clean(self):
        data = super().clean()
        if not data.get('file') and not data.get('url'):
            raise ValidationError('Добавьте файл или ссылку.')
        if data.get('file') and data['file'].size > 20 * 1024 * 1024:
            self.add_error('file', 'Максимальный размер — 20 МБ.')
        return data


class AssignmentTemplateForm(forms.ModelForm):
    class Meta:
        model = AssignmentTemplate
        fields = ['heading', 'introduction', 'footer']
        widgets = {'introduction': forms.Textarea(attrs={'rows': 5}), 'footer': forms.Textarea(attrs={'rows': 3})}


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['topic', 'programs', 'courses', 'text', 'active']
        widgets = {'text': forms.Textarea(attrs={'rows': 6})}
    def clean_courses(self):
        value = self.cleaned_data['courses'].replace(' ', '')
        if not value or any(c not in ('1', '2', '3') for c in value.split(',')):
            raise ValidationError('Укажите курсы от 1 до 3 через запятую.')
        return ','.join(sorted(set(value.split(','))))


class AllocationForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ['supervisor']
        labels = {'supervisor': 'Преподаватель-руководитель'}
    def __init__(self, *args, department, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supervisor'].queryset = Profile.objects.filter(role=Profile.Role.TEACHER, department=department, user__is_active=True).order_by('full_name')


class UniversityAccountForm(forms.Form):
    username = forms.CharField(label='Университетский логин', max_length=150, validators=User._meta.get_field('username').validators, help_text='Идентификатор из системы входа КубГУ. Локальный пароль не создаётся.')
    full_name = forms.CharField(label='ФИО полностью', max_length=250)


class StudentAddForm(UniversityAccountForm):
    supervisor = forms.ModelChoiceField(label='Преподаватель-руководитель', queryset=Profile.objects.none())
    def __init__(self, *args, department, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supervisor'].queryset = Profile.objects.filter(role=Profile.Role.TEACHER, department=department, user__is_active=True).order_by('full_name')


class BulkAllocationForm(forms.Form):
    students = forms.ModelMultipleChoiceField(label='Студенты', queryset=Enrollment.objects.none(), error_messages={'required': 'Выберите хотя бы одного студента.', 'invalid_choice': 'В списке есть недоступный студент.'})
    supervisor = forms.ModelChoiceField(label='Руководитель для выбранных студентов', queryset=Profile.objects.none())
    def __init__(self, *args, cohort, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['students'].queryset = cohort.enrollments.filter(department=cohort.department)
        self.fields['supervisor'].queryset = Profile.objects.filter(role=Profile.Role.TEACHER, department=cohort.department, user__is_active=True).order_by('full_name')
