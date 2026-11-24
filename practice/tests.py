from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zipfile import ZipFile
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils.html import escape
from docx import Document
from .documents import variant_document
from .models import AssignmentTemplate, Cohort, Enrollment, Profile, Program, Report, Task, Topic, Variant, VariantItem
from .services import add_student, generate_variants, generation_readiness, import_students, provision_account


class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def person(login, role, dept='ФАА'):
            user = User.objects.create_user(username=login, password='TestPassword349!')
            return Profile.objects.create(user=user, full_name=login, role=role, department=dept)
        cls.head = person('head', 'head')
        cls.teacher = person('teacher', 'teacher')
        cls.peer = person('peer', 'teacher')
        cls.otherhead = person('otherhead', 'head', 'ФМА')
        cls.otherteacher = person('otherteacher', 'teacher', 'ФМА')
        cls.student = person('student', 'student')
        cls.student2 = person('student2', 'student')
        cls.peerstudent = person('peerstudent', 'student')
        cls.outsider = person('outsider', 'student', 'ФМА')
        cls.program = Program.objects.create(code='01.03.02', name='ПМИ', competencies='УК-1 (тест)')
        cls.topic = Topic.objects.create(name='Алгебра')
        cls.group = Cohort.objects.create(name='21', department='ФАА', program=cls.program, course=2, academic_year=2026, start_date=date(2027, 6, 1), end_date=date(2027, 6, 28))
        cls.group.topics.add(cls.topic)
        cls.othergroup = Cohort.objects.create(name='22', department='ФМА', program=cls.program, course=2, academic_year=2026, start_date=date(2027, 6, 1), end_date=date(2027, 6, 28))
        cls.othergroup.topics.add(cls.topic)
        cls.enrollment = Enrollment.objects.create(cohort=cls.group, student=cls.student, supervisor=cls.teacher, department='ФАА')
        cls.enrollment2 = Enrollment.objects.create(cohort=cls.group, student=cls.student2, supervisor=cls.teacher, department='ФАА')
        cls.peer_enrollment = Enrollment.objects.create(cohort=cls.group, student=cls.peerstudent, supervisor=cls.peer, department='ФАА')
        cls.foreign_enrollment = Enrollment.objects.create(cohort=cls.othergroup, student=cls.outsider, supervisor=cls.otherteacher, department='ФМА')
        Task.objects.bulk_create([Task(topic=cls.topic, text=f'Найдите корни x² − {i} = 0.') for i in range(1, 31)])

    def setUp(self):
        cache.clear()
        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        override = override_settings(MEDIA_ROOT=self.tempdir.name)
        override.enable()
        self.addCleanup(override.disable)

    def login(self, profile):
        self.client.force_login(profile.user)

    def docx(self):
        stream = BytesIO()
        Document().save(stream)
        return SimpleUploadedFile('report.docx', stream.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    def generate(self):
        return generate_variants(self.group.pk, self.teacher)

    def test_all_role_pages_render(self):
        self.generate()
        for profile, paths in [
            (self.head, ['/', '/groups/', f'/groups/{self.group.pk}/', f'/groups/{self.group.pk}/edit/', f'/groups/{self.group.pk}/students/new/', '/teachers/', '/teachers/new/', '/groups/new/', '/bank/', '/bank/new/', '/assignment-template/', '/materials/', '/materials/new/', f'/students/{self.enrollment.pk}/']),
            (self.teacher, ['/', '/groups/', f'/groups/{self.group.pk}/', '/bank/', '/materials/', f'/students/{self.enrollment.pk}/']),
            (self.student, ['/', '/materials/', f'/students/{self.enrollment.pk}/']),
        ]:
            self.login(profile)
            for path in paths:
                with self.subTest(role=profile.role, path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_student_only_sees_own_data(self):
        self.login(self.student)
        self.assertNotContains(self.client.get('/'), 'peerstudent')
        for path in [f'/students/{self.enrollment2.pk}/', f'/students/{self.foreign_enrollment.pk}/']:
            self.assertEqual(self.client.get(path).status_code, 404)
        for path in ['/groups/', '/bank/', '/assignment-template/']:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_teacher_only_own_students(self):
        self.login(self.teacher)
        response = self.client.get('/')
        self.assertContains(response, 'student2')
        self.assertNotContains(response, 'peerstudent')
        self.assertEqual(self.client.get(f'/students/{self.peer_enrollment.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/assignment-template/').status_code, 403)
        self.assertEqual(self.client.get('/groups/new/').status_code, 403)

    def test_head_cannot_access_other_department(self):
        self.login(self.head)
        self.assertEqual(self.client.get(f'/students/{self.foreign_enrollment.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/groups/{self.othergroup.pk}/').status_code, 404)
        self.assertEqual(self.client.post(f'/groups/{self.group.pk}/generate/').status_code, 403)

    def test_generation_own_students_idempotent_and_unique(self):
        self.assertEqual(self.generate(), 2)
        self.assertEqual(self.generate(), 0)
        self.assertFalse(Variant.objects.filter(enrollment=self.peer_enrollment).exists())
        generate_variants(self.group.pk, self.peer)
        generate_variants(self.othergroup.pk, self.otherteacher)
        self.assertEqual(VariantItem.objects.count(), 4)
        self.assertEqual(len(set(VariantItem.objects.values_list('task_id', flat=True))), 4)

    def test_variant_snapshot_survives_bank_and_template_edits(self):
        template = AssignmentTemplate.objects.create(department='ФАА', heading='Первоначальный бланк')
        self.generate()
        variant = Variant.objects.get(enrollment=self.enrollment)
        item = variant.items.get()
        original = item.text
        Task.objects.filter(pk=item.task_id).update(text='Новое условие')
        template.heading = 'Новый бланк'
        template.save()
        item.refresh_from_db()
        self.assertEqual(item.text, original)
        self.assertEqual(variant.metadata['heading'], 'Первоначальный бланк')
        with ZipFile(variant_document(variant, full=True)) as archive:
            xml = archive.read('word/document.xml').decode()
            for text in [original, 'Лист инструктажа', 'Оценочный лист', 'Первоначальный бланк']:
                self.assertIn(text, xml)

    def test_generation_rollback_when_topic_too_small(self):
        topic = Topic.objects.create(name='Пустая тема')
        self.group.topics.add(topic)
        with self.assertRaises(ValidationError):
            self.generate()
        self.assertEqual(Variant.objects.count(), 0)

    def test_generation_insufficient_unused_tasks(self):
        self.generate()
        used = VariantItem.objects.values_list('task_id', flat=True)
        Task.objects.exclude(pk__in=used).delete()
        # Eligible count itself is now below 25; no partial variant may be issued.
        with self.assertRaises(ValidationError):
            generate_variants(self.group.pk, self.peer)
        self.assertFalse(Variant.objects.filter(enrollment=self.peer_enrollment).exists())

    def test_teacher_generate_route_multiple_students(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(f'/groups/{self.group.pk}/generate/').status_code, 405)
        self.assertEqual(self.client.post(f'/groups/{self.group.pk}/generate/').status_code, 302)
        self.assertEqual(Variant.objects.count(), 2)

    @patch('practice.views.generate_variants', side_effect=OperationalError('database is locked'))
    def test_concurrent_generation_gives_retry_message(self, generate_mock):
        self.login(self.teacher)
        response = self.client.post(f'/groups/{self.group.pk}/generate/', follow=True)
        self.assertContains(response, 'повторите формирование')
        self.assertEqual(Variant.objects.count(), 0)

    def test_upload_review_revision_and_acceptance_flow(self):
        self.generate()
        self.login(self.student)
        url = f'/students/{self.enrollment.pk}/'
        self.assertEqual(self.client.post(url, {'file': self.docx()}).status_code, 302)
        report = Report.objects.get()
        self.client.post(url, {'file': self.docx()})
        self.assertEqual(Report.objects.count(), 1)
        self.login(self.teacher)
        self.client.post(f'/reports/{report.pk}/review/', {'status': 'revision', 'comment': 'Дополните решение'})
        report.refresh_from_db()
        self.assertEqual(report.status, 'revision')
        self.login(self.student)
        self.client.post(url, {'file': self.docx()})
        latest = Report.objects.first()
        self.assertEqual(Report.objects.count(), 2)
        self.login(self.teacher)
        response = self.client.post(f'/reports/{report.pk}/review/', {'status': 'accepted', 'grade': 5})
        self.assertContains(response, 'предыдущая версия')
        self.client.post(f'/reports/{latest.pk}/review/', {'status': 'accepted', 'grade': 5, 'comment': 'Принято'})
        latest.refresh_from_db()
        self.assertEqual(latest.status, 'accepted')
        self.assertEqual(latest.grade, 5)
        self.login(self.student)
        self.client.post(url, {'file': self.docx()})
        self.assertEqual(Report.objects.count(), 2)

    def test_upload_rejects_fake_document_and_missing_variant(self):
        self.login(self.student)
        response = self.client.post(f'/students/{self.enrollment.pk}/', {'file': SimpleUploadedFile('bad.pdf', b'not PDF')})
        self.assertContains(response, 'корректный PDF')
        response = self.client.post(f'/students/{self.enrollment.pk}/', {'file': self.docx()})
        self.assertContains(response, 'Дождитесь выдачи')
        self.assertEqual(Report.objects.count(), 0)

    def test_report_download_access_and_review_permissions(self):
        report = Report.objects.create(enrollment=self.enrollment, file=self.docx(), original_name='report.docx')
        for profile, expected in [(self.student, 200), (self.teacher, 200), (self.head, 200), (self.peer, 404), (self.student2, 404), (self.otherhead, 404)]:
            self.login(profile)
            response = self.client.get(f'/reports/{report.pk}/download/')
            self.assertEqual(response.status_code, expected)
            response.close()
        self.login(self.student)
        self.assertEqual(self.client.post(f'/reports/{report.pk}/review/', {'status': 'accepted', 'grade': 5}).status_code, 403)

    def test_allocation_changes_access_and_preserves_variant(self):
        self.generate()
        variant_pk = Variant.objects.get(enrollment=self.enrollment).pk
        self.login(self.head)
        self.client.post(f'/students/{self.enrollment.pk}/allocate/', {'supervisor': self.otherteacher.pk})
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.supervisor, self.teacher)
        self.client.post(f'/students/{self.enrollment.pk}/allocate/', {'supervisor': self.peer.pk})
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.supervisor, self.peer)
        self.assertEqual(self.enrollment.variant.pk, variant_pk)
        self.login(self.teacher)
        self.assertEqual(self.client.get(f'/students/{self.enrollment.pk}/').status_code, 404)
        self.login(self.peer)
        self.assertEqual(self.client.get(f'/students/{self.enrollment.pk}/').status_code, 200)

    def test_import_is_idempotent_and_atomic(self):
        header = 'student_login;student_name;supervisor_login;supervisor_name;department\n'
        row = 'newstudent;Новый студент;teacher;teacher;ФАА\n'
        def upload(text):
            return SimpleUploadedFile('students.csv', text.encode('utf-8-sig'))
        self.assertEqual(import_students(self.group, upload(header + row)), 1)
        self.assertEqual(import_students(self.group, upload(header + row)), 0)
        with self.assertRaises(ValidationError):
            import_students(self.group, upload(header + 'rollback;Новый;teacher;teacher;ФАА\n' + 'student;student;teacher;teacher;ФМА\n'))
        self.assertFalse(User.objects.filter(username='rollback').exists())
        with self.assertRaises(ValidationError):
            import_students(self.group, upload(''))

    def test_import_cannot_change_role_or_department(self):
        content = 'student_login;student_name;supervisor_login;supervisor_name;department\nhead;head;teacher;teacher;ФАА\n'
        with self.assertRaises(ValidationError):
            import_students(self.group, SimpleUploadedFile('students.csv', content.encode('utf-8')))
        self.head.refresh_from_db()
        self.assertEqual(self.head.role, 'head')

    def test_additional_student_does_not_change_existing_variants(self):
        self.generate()
        original = list(VariantItem.objects.values_list('id', 'task_id', 'text'))
        user = User.objects.create(username='additional')
        profile = Profile.objects.create(user=user, full_name='Дополнительный студент', department='ФАА')
        Enrollment.objects.create(student=profile, supervisor=self.teacher, cohort=self.group, department='ФАА')
        self.assertEqual(self.generate(), 1)
        self.assertEqual(list(VariantItem.objects.order_by('id').values_list('id', 'task_id', 'text'))[:len(original)], original)

    def test_unauthenticated_redirects_and_csrf(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher.user)
        self.assertEqual(client.post(f'/groups/{self.group.pk}/generate/').status_code, 403)

    def test_no_profile_cannot_access(self):
        user = User.objects.create_user('unassigned')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/').status_code, 403)

    def test_oidc_disabled_is_not_fake_login(self):
        with override_settings(KUBSU_CLIENT_ID='', KUBSU_CLIENT_SECRET='', KUBSU_OIDC_METADATA_URL=''):
            self.assertEqual(self.client.get('/auth/kubsu/').status_code, 302)
            self.assertNotIn('_auth_user_id', self.client.session)

    @patch('practice.auth.oidc_client')
    def test_oidc_binds_only_preloaded_login_and_preserves_role(self, factory):
        client = Mock()
        client.authorize_access_token.return_value = {'id_token': 'verified-by-authlib', 'userinfo': {'sub': 'subject-1', 'iss': 'https://id.example.edu', 'preferred_username': 'student', 'role': 'head'}}
        factory.return_value = client
        self.client.get('/auth/kubsu/callback/')
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'student')
        self.assertEqual(self.student.oidc_subject, 'subject-1')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.student.user_id)

    @patch('practice.auth.oidc_client')
    def test_oidc_rejects_unknown_or_missing_claims(self, factory):
        client = Mock()
        factory.return_value = client
        for claims in [{'sub': 'x', 'iss': 'https://id.example.edu', 'preferred_username': 'unknown'}, {'preferred_username': 'head'}]:
            client.authorize_access_token.return_value = {'id_token': 'verified-by-authlib', 'userinfo': claims}
            self.client.get('/auth/kubsu/callback/')
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_head_adds_student_with_fixed_role_and_department(self):
        self.login(self.head)
        response = self.client.post(f'/groups/{self.group.pk}/students/new/', {'username': 'new.student', 'full_name': 'Новый Студент', 'supervisor': self.teacher.pk, 'role': 'head', 'department': 'ФМА'})
        self.assertEqual(response.status_code, 302)
        profile = Profile.objects.get(user__username='new.student')
        self.assertEqual(profile.role, 'student')
        self.assertEqual(profile.department, 'ФАА')
        self.assertFalse(profile.user.has_usable_password())
        self.assertEqual(profile.enrollments.get().supervisor, self.teacher)

    def test_manual_student_add_rejects_foreign_teacher(self):
        self.login(self.head)
        response = self.client.post(f'/groups/{self.group.pk}/students/new/', {'username': 'illegal', 'full_name': 'Новый', 'supervisor': self.otherteacher.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='illegal').exists())

    def test_manual_student_add_is_idempotent_and_preserves_assignment(self):
        self.generate()
        original = self.enrollment.variant.pk
        enrollment, created = add_student(self.group, 'student', 'student', self.teacher)
        self.assertFalse(created)
        self.assertEqual(enrollment.variant.pk, original)
        with self.assertRaises(ValidationError):
            add_student(self.group, 'student', 'student', self.peer)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.supervisor, self.teacher)

    def test_head_adds_teacher_and_list_is_scoped(self):
        self.login(self.head)
        self.assertEqual(self.client.post('/teachers/new/', {'username': 'new.teacher', 'full_name': 'Новый Преподаватель', 'role': 'head'}).status_code, 302)
        profile = Profile.objects.get(user__username='new.teacher')
        self.assertEqual(profile.role, 'teacher')
        self.assertEqual(profile.department, 'ФАА')
        self.assertFalse(profile.user.has_usable_password())
        response = self.client.get('/teachers/')
        self.assertContains(response, 'Новый Преподаватель')
        self.assertNotContains(response, 'otherteacher')

    def test_provision_cannot_claim_technical_user(self):
        reserved = User.objects.create_superuser('reserved', password='TechnicalPassword29!')
        with self.assertRaises(ValidationError):
            provision_account('reserved', 'Reserved', 'teacher', 'ФАА')
        self.assertFalse(Profile.objects.filter(user=reserved).exists())

    def test_bulk_allocation_preserves_variants_and_changes_access(self):
        self.generate()
        original = list(VariantItem.objects.values_list('id', 'task_id', 'text'))
        self.login(self.head)
        response = self.client.post(f'/groups/{self.group.pk}/allocate/', {'students': [self.enrollment.pk, self.enrollment2.pk], 'supervisor': self.peer.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Enrollment.objects.filter(pk__in=[self.enrollment.pk, self.enrollment2.pk], supervisor=self.peer).count(), 2)
        self.assertEqual(list(VariantItem.objects.values_list('id', 'task_id', 'text')), original)
        self.login(self.teacher)
        self.assertEqual(self.client.get(f'/students/{self.enrollment.pk}/').status_code, 404)

    def test_bulk_allocation_with_foreign_student_is_atomic(self):
        self.login(self.head)
        response = self.client.post(f'/groups/{self.group.pk}/allocate/', {'students': [self.enrollment.pk, self.foreign_enrollment.pk], 'supervisor': self.peer.pk}, follow=True)
        self.assertContains(response, 'недоступный студент')
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.supervisor, self.teacher)
        self.client.post(f'/groups/{self.group.pk}/allocate/', {'students': [self.enrollment.pk], 'supervisor': self.otherteacher.pk})
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.supervisor, self.teacher)

    def test_group_edit_cannot_move_students_to_another_year(self):
        self.generate()
        before = self.enrollment.variant.metadata.copy()
        self.login(self.head)
        response = self.client.post(f'/groups/{self.group.pk}/edit/', {'name': 'Новое название', 'program': self.program.pk, 'course': 3, 'academic_year': 2029, 'start_date': '2027-06-02', 'end_date': '2027-06-29', 'practice_title': 'Новая практика', 'topics': [self.topic.pk]})
        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.academic_year, 2026)
        self.assertEqual(self.group.name, 'Новое название')
        self.enrollment.variant.refresh_from_db()
        self.assertEqual(self.enrollment.variant.metadata, before)

    def test_new_management_endpoints_are_head_only(self):
        for profile in [self.teacher, self.student]:
            self.login(profile)
            for path in ['/teachers/', '/teachers/new/', f'/groups/{self.group.pk}/edit/', f'/groups/{self.group.pk}/students/new/']:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post(f'/groups/{self.group.pk}/allocate/', {'students': [self.enrollment.pk], 'supervisor': self.peer.pk}).status_code, 403)
        self.login(self.otherhead)
        self.assertEqual(self.client.get(f'/groups/{self.group.pk}/edit/').status_code, 404)

    def test_readiness_matches_generation_eligibility_and_capacity(self):
        ready = generation_readiness(self.group, self.teacher)
        self.assertTrue(ready['ready'])
        self.assertEqual(ready['pending'], 2)
        self.assertEqual(ready['topics'][0]['total'], 30)
        self.generate()
        ready = generation_readiness(self.group, self.teacher)
        self.assertFalse(ready['ready'])
        self.assertEqual(ready['pending'], 0)
        self.assertEqual(ready['topics'][0]['available'], 28)
        Task.objects.create(topic=self.topic, department='ФМА', text='Чужая задача')
        Task.objects.create(topic=self.topic, courses='3', text='Другой курс')
        self.assertEqual(generation_readiness(self.group, self.peer)['topics'][0]['total'], 30)

    def test_malformed_csv_is_a_validation_error(self):
        content = 'student_login;student_name;supervisor_login;supervisor_name;department\n"unclosed'
        with self.assertRaises(ValidationError):
            import_students(self.group, SimpleUploadedFile('bad.csv', content.encode()))

    def test_search_russian_names_ignores_case(self):
        self.student.full_name = 'Иванов Иван Иванович'
        self.student.save()
        self.login(self.teacher)
        response = self.client.get('/', {'q': 'иванов'})
        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, 'Иванов Иван Иванович')
        self.login(self.peer)
        self.assertEqual(self.client.get('/', {'q': 'иванов'}).context['total'], 0)

    def test_search_task_text_ignores_cyrillic_case_and_treats_wildcards_literally(self):
        Task.objects.create(topic=self.topic, text='Изучите рост на 100% за период')
        self.login(self.head)
        self.assertEqual(self.client.get('/bank/', {'q': 'изучите'}).context['task_count'], 1)
        self.assertEqual(self.client.get('/bank/', {'q': '100%'}).context['task_count'], 1)
        self.assertEqual(self.client.get('/bank/', {'q': '100_'}).context['task_count'], 0)

    def test_math_task_preserves_multiline_latex_and_escapes_html(self):
        text = '\\[\\begin{pmatrix}\n1 & 2 \\\\\n3 & 4\n\\end{pmatrix}\\]\n<script>alert(1)</script>'
        task = Task.objects.create(topic=self.topic, text=text)
        self.login(self.head)
        response = self.client.get('/bank/', {'q': 'pmatrix'})
        self.assertContains(response, 'data-math')
        self.assertContains(response, '1 &amp; 2')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '<div class="math-content" data-math>' + escape(text) + '</div>')
        variant = Variant.objects.create(enrollment=self.enrollment, metadata={})
        VariantItem.objects.create(variant=variant, task=task, academic_year=2026, topic_name=self.topic.name, text=text)
        self.login(self.student)
        response = self.client.get(f'/students/{self.enrollment.pk}/')
        self.assertContains(response, 'vendor/katex/katex.min.js')
        self.assertContains(response, '1 &amp; 2')
        self.assertNotContains(response, '<script>alert(1)</script>')
