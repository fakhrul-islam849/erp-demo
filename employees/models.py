import uuid

from django.conf import settings
from django.db import models
from common.utils import compress_image
class Employee(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='employee'
        )
    phone = models.CharField(max_length=20)
    dob = models.DateField()
    photo = models.ImageField(upload_to='employees/photos/')
    present_address = models.TextField()
    permanent_address = models.TextField()
    designation = models.CharField(max_length=100)
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    id_card_front = models.ImageField(upload_to='employees/id_cards/')
    id_card_back = models.ImageField(upload_to='employees/id_cards/')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'employee'

    def save(self, *args, **kwargs):
        if self.photo and not self.photo._committed:
            self.photo = compress_image(self.photo, max_dimension=500, quality=80)
        if self.id_card_front and not self.id_card_front._committed:
            self.id_card_front = compress_image(self.id_card_front, max_dimension=1600, quality=80)
        if self.id_card_back and not self.id_card_back._committed:
            self.id_card_back = compress_image(self.id_card_back, max_dimension=1600, quality=80)
        super().save(*args, **kwargs)