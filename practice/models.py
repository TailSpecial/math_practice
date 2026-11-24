import uuid
from pathlib import Path
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


def private_path(instance, filename):
    return f'{instance._meta.model_name}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Profile(models.Model):
    class Role(models.TextChoices):
        STUDENT = 'student', 'Студент'
        TEACHER = 'teacher', 'Преподаватель'
        HEAD = 'head', 'Заведующий кафедрой'
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField('ФИО', max_length=250)
    role = models.CharField('Роль', max_length=20, choices=Role.choices, default=Role.STUDENT)
    department = models.CharField('Кафедра', max_length=200, blank=True)
    oidc_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
    oidc_issuer = models.URLField(blank=True)
    def __str__(self):
        return self.full_name


class Program(models.Model):
    code = models.CharField('Код', max_length=30, unique=True)
    name = models.CharField('Направление', max_length=250)
    competencies = models.TextField('Актуальные компетенции (по одной на строку)')
    def __str__(self):
        return f'{self.code} · {self.name}'


class Topic(models.Model):
    name = models.CharField('Тема', max_length=200, unique=True)
    description = models.TextField('Описание', blank=True)
    def __str__(self):
        return self.name


class Task(models.Model):
    department = models.CharField('Кафедра (пусто — общий банк)', max_length=200, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, verbose_name='Тема')
    programs = models.ManyToManyField(Program, blank=True, verbose_name='Направления (пусто — все)')
    courses = models.CharField('Курсы через запятую', max_length=10, default='1,2,3')
    text = models.TextField('Условие')
    active = models.BooleanField('Активна', default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['topic', 'text'], name='unique_topic_text')]
    def __str__(self):
        return f'{self.topic}: {self.text[:70]}'


class Cohort(models.Model):
    department = models.CharField('Кафедра', max_length=200)
    name = models.CharField('Группа', max_length=100)
    program = models.ForeignKey(Program, on_delete=models.PROTECT, verbose_name='Направление')
    course = models.PositiveSmallIntegerField('Курс', validators=[MinValueValidator(1), MaxValueValidator(3)])
    academic_year = models.PositiveIntegerField('Начало учебного года', default=2026)
    start_date = models.DateField('Начало практики')
    end_date = models.DateField('Конец практики')
    practice_title = models.CharField('Название практики', max_length=500, default='Учебная практика (научно-исследовательская работа (получение первичных навыков научно-исследовательской работы))')
    topics = models.ManyToManyField(Topic, verbose_name='Темы')
    def __str__(self):
        return f'{self.name} · {self.academic_year}/{self.academic_year + 1}'


class Enrollment(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.PROTECT, related_name='enrollments')
    student = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name='enrollments')
    supervisor = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name='supervised')
    department = models.CharField('Кафедра', max_length=200)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['cohort', 'student'], name='unique_cohort_student')]
        ordering = ['student__full_name']
    def __str__(self):
        return f'{self.student} · {self.cohort}'


class Variant(models.Model):
    enrollment = models.OneToOneField(Enrollment, on_delete=models.PROTECT, related_name='variant')
    created_at = models.DateTimeField(auto_now_add=True)
    # Snapshot guarantees downloaded documents don't change after task edits.
    metadata = models.JSONField(default=dict)
    def __str__(self):
        return f'Вариант {self.pk:04d} · {self.enrollment.student}'


class VariantItem(models.Model):
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name='items')
    task = models.ForeignKey(Task, on_delete=models.PROTECT)
    academic_year = models.PositiveIntegerField()
    topic_name = models.CharField(max_length=200)
    text = models.TextField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['academic_year', 'task'], name='unique_task_per_year')]
        ordering = ['id']


class Report(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'На проверке'
        REVISION = 'revision', 'На доработке'
        ACCEPTED = 'accepted', 'Принят'
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name='reports')
    file = models.FileField(upload_to=private_path)
    original_name = models.CharField(max_length=250)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    comment = models.TextField('Комментарий', blank=True)
    grade = models.PositiveSmallIntegerField('Оценка', null=True, blank=True, validators=[MinValueValidator(2), MaxValueValidator(5)])
    reviewed_by = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-uploaded_at', '-id']


class Material(models.Model):
    title = models.CharField('Название', max_length=250)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='Тема')
    description = models.TextField('Описание', blank=True)
    file = models.FileField('Файл', upload_to=private_path, blank=True)
    url = models.URLField('Ссылка', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.title


class AssignmentTemplate(models.Model):
    department = models.CharField('Кафедра', max_length=200, unique=True)
    heading = models.CharField('Заголовок бланка', max_length=250, default='Индивидуальное задание')
    introduction = models.TextField('Инструкция перед заданиями', blank=True, default='Выполните задания своего варианта. Решения оформите в отчёте по практике.')
    footer = models.TextField('Текст после заданий', blank=True, default='Отчёт загрузите в личном кабинете в установленные сроки.')
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.department
