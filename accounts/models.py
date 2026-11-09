import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('user_type', User.UserType.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)

class User(AbstractUser):
    class UserType(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        EMPLOYEE = 'employee', 'Employee'

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.EMPLOYEE)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_device = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

# Create your models here.
