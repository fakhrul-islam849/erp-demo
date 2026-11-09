from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'user_type', 'is_active', 'last_login')
    list_filter = ('user_type', 'is_active', 'is_staff')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Extra info', {'fields': ('uid', 'user_type', 'last_ip', 'last_device')}),
    )
    readonly_fields = ('uid', 'last_ip', 'last_device', 'last_login', 'date_joined')