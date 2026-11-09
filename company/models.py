from django.db import models

from common.utils import compress_image


class Company(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()
    contact_number = models.CharField(max_length=20)
    email = models.EmailField()
    logo = models.ImageField(upload_to='company/')
    company_number = models.CharField(max_length=100)
    trademark_number = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'company'

    def save(self, *args, **kwargs):
        self.pk = 1
        if self.logo and not self.logo._committed:
            self.logo = compress_image(self.logo, max_dimension=800, quality=85)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        return cls.objects.first()