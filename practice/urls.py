from django.contrib.auth.views import LogoutView
from django.urls import path
from . import auth, views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.PortalLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('auth/kubsu/', auth.kubsu_login, name='kubsu_login'),
    path('auth/kubsu/callback/', auth.kubsu_callback, name='kubsu_callback'),
    path('students/<int:pk>/', views.enrollment_detail, name='enrollment'),
    path('students/<int:pk>/allocate/', views.allocate, name='allocate'),
    path('students/<int:pk>/document/<str:kind>/', views.download_variant, name='document'),
    path('reports/<int:pk>/download/', views.download_report, name='report_download'),
    path('reports/<int:pk>/review/', views.review_report, name='review'),
    path('groups/', views.groups, name='groups'),
    path('groups/new/', views.group_create, name='group_create'),
    path('groups/<int:pk>/', views.group_detail, name='group'),
    path('groups/<int:pk>/edit/', views.group_edit, name='group_edit'),
    path('groups/<int:pk>/students/new/', views.student_add, name='student_add'),
    path('groups/<int:pk>/allocate/', views.bulk_allocate, name='bulk_allocate'),
    path('groups/<int:pk>/generate/', views.generate, name='generate'),
    path('students-template.csv', views.csv_template, name='csv_template'),
    path('teachers/', views.teachers, name='teachers'),
    path('teachers/new/', views.teacher_add, name='teacher_add'),
    path('bank/', views.task_bank, name='bank'),
    path('bank/new/', views.task_edit, name='task_create'),
    path('bank/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('assignment-template/', views.assignment_template, name='assignment_template'),
    path('materials/', views.materials, name='materials'),
    path('materials/new/', views.material_create, name='material_create'),
    path('materials/<int:pk>/download/', views.material_download, name='material_download'),
]
