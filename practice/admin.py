from django.contrib import admin
from .models import AssignmentTemplate, Cohort, Enrollment, Material, Profile, Program, Report, Task, Topic, Variant, VariantItem

admin.site.site_header = 'Практика · техническое администрирование'

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user', 'role', 'department']
    list_filter = ['role', 'department']
    search_fields = ['full_name', 'user__username']

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['id', 'topic', 'department', 'courses', 'active']
    list_filter = ['topic', 'department', 'active']
    search_fields = ['text']
    filter_horizontal = ['programs']

@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ['name', 'department', 'program', 'course', 'academic_year']
    filter_horizontal = ['topics']

@admin.register(Variant, VariantItem)
class ImmutableAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register([Program, Topic, Enrollment, Report, Material, AssignmentTemplate])
