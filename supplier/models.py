from django.db import models

from common.constants import COUNTRY_CHOICES


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    country = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'supplier'

    def __str__(self):
        return self.name
