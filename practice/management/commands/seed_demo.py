from datetime import date
from io import BytesIO
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from docx import Document
from practice.models import AssignmentTemplate, Cohort, Enrollment, Material, Profile, Program, Report, Task, Topic
from practice.services import generate_variants


class Command(BaseCommand):
    help = 'Создать демонстрационные аккаунты и банк задач (только DEBUG=1)'
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Демонстрационные аккаунты разрешены только в DEBUG=1.')
        def profile(login, name, role, department='ФАА'):
            user, created = User.objects.get_or_create(username=login)
            if created:
                user.set_password('Practice2026!')
                user.save()
            result, _ = Profile.objects.get_or_create(user=user, defaults={'full_name': name, 'role': role, 'department': department})
            return result
        head = profile('head', 'Соколова Елена Викторовна', 'head')
        teacher = profile('teacher', 'Петров Андрей Сергеевич', 'teacher')
        teacher2 = profile('teacher2', 'Волкова Мария Игоревна', 'teacher')
        program, _ = Program.objects.get_or_create(code='01.03.02', defaults={'name': 'Прикладная математика и информатика', 'competencies': 'ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ: замените этот текст актуальными компетенциями из утверждённого учебного плана.\nУК-1 — системное и критическое мышление (пример).\nОПК-1 — применение фундаментальных знаний (пример).'})
        specifications = [
            ('Математический анализ', lambda n: f'Исследуйте функцию f(x) = (x² + {n}) / (x − {n + 1}). Найдите область определения, асимптоты, промежутки монотонности и экстремумы. Постройте график и обоснуйте выводы.'),
            ('Алгебра', lambda n: f'Для матрицы A = [[{n + 2}, 1, 0], [1, {n + 2}, 1], [0, 1, {n + 2}]] найдите определитель, собственные значения и собственные векторы. Исследуйте диагонализируемость и запишите A в собственном базисе.'),
            ('Дифференциальные уравнения', lambda n: f'Решите задачу Коши y\' + {n}y = exp(x), y(0) = {n + 1}. Проверьте решение подстановкой. Исследуйте поведение решения при x → +∞ и зависимость от начального условия.'),
            ('Уравнения в частных производных', lambda n: f'Методом разделения переменных решите уравнение теплопроводности u_t = {n}u_xx на 0 < x < π с условиями u(0,t)=u(π,t)=0 и u(x,0)=sin({n}x)+sin({n + 1}x). Обоснуйте выполнение условий.'),
            ('Программирование', lambda n: f'Реализуйте численное интегрирование функции f(x)=exp(−{n}x²) на [0,1] методами трапеций и Симпсона. Сравните результаты при 20, 40 и 80 разбиениях. Оцените погрешность по правилу Рунге и приложите исходный код.'),
            ('Теория вероятностей', lambda n: f'Вероятность успеха в независимом испытании равна {n}/({n}+10). Для 30 испытаний найдите математическое ожидание, дисперсию и вероятность ровно 10 успехов. Сопоставьте точный результат с нормальным приближением.')]
        topics = []
        for name, factory in specifications:
            topic, _ = Topic.objects.get_or_create(name=name)
            topics.append(topic)
            for n in range(1, 41):
                Task.objects.get_or_create(topic=topic, text=factory(n), defaults={'courses': '1,2,3'})
        cohort, created = Cohort.objects.get_or_create(name='21-ПМИ', academic_year=2026, department='ФАА', defaults={'program': program, 'course': 2, 'start_date': date(2027, 6, 1), 'end_date': date(2027, 6, 28)})
        if created:
            cohort.topics.set(topics[:3] + topics[4:5])
        AssignmentTemplate.objects.get_or_create(department='ФАА')
        names = ['Иванов Иван Иванович', 'Алексеева Анна Дмитриевна', 'Бондаренко Артём Олегович', 'Васильева Софья Романовна', 'Григорьев Максим Андреевич', 'Дмитриева Полина Ильинична', 'Егоров Никита Павлович', 'Жукова Дарья Сергеевна']
        enrollments = []
        for i, name in enumerate(names):
            student = profile('student' if i == 0 else f'student{i + 1}', name, 'student')
            enrollment, _ = Enrollment.objects.get_or_create(cohort=cohort, student=student, defaults={'supervisor': teacher if i < 6 else teacher2, 'department': 'ФАА'})
            enrollments.append(enrollment)
        generate_variants(cohort.pk, teacher)
        generate_variants(cohort.pk, teacher2)
        for i, status in [(0, 'revision'), (1, 'submitted'), (2, 'accepted')]:
            enrollment = enrollments[i]
            if not enrollment.reports.exists():
                doc = Document()
                doc.add_heading('Демонстрационный отчёт', 0)
                doc.add_paragraph('Пример загрузки для проверки рабочего процесса. Не является выполненным заданием.')
                stream = BytesIO()
                doc.save(stream)
                Report.objects.create(enrollment=enrollment, file=ContentFile(stream.getvalue(), name='report.docx'), original_name='Отчёт по практике.docx', status=status, comment='Добавьте обоснование полученных результатов.' if status == 'revision' else '', grade=5 if status == 'accepted' else None, reviewed_by=teacher if status != 'submitted' else None)
        if not Material.objects.filter(title='Как оформить отчёт по практике').exists():
            doc = Document()
            doc.add_heading('Рекомендации по оформлению отчёта', 0)
            doc.add_paragraph('Демонстрационное пособие. Утверждённые кафедрой требования имеют приоритет.')
            for text in ['Скачайте бланки и индивидуальное задание в личном кабинете.', 'Для каждой задачи приведите условие, метод решения, подробное решение и проверку.', 'Включите выводы, список источников и исходный код программ.', 'Загрузите отчёт в PDF или DOCX и дождитесь проверки преподавателя.']:
                doc.add_paragraph(text, style='List Number')
            stream = BytesIO()
            doc.save(stream)
            Material.objects.create(title='Как оформить отчёт по практике', description='Памятка по структуре отчёта и порядку сдачи. Демонстрационный материал.', file=ContentFile(stream.getvalue(), name='guide.docx'))
        self.stdout.write(self.style.SUCCESS('Демо готово: head, teacher, teacher2, student. Пароль новых аккаунтов: Practice2026!'))
