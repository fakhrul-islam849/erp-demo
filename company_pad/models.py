import secrets
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

ATTACHMENT_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'heic']


class Category(models.Model):
    name = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Pad(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        AWAITING_SIGNATURE = 'awaiting_signature', 'Awaiting Signature'
        SIGNED = 'signed', 'Signed'
        CANCELLED = 'cancelled', 'Cancelled'

    class PartyBType(models.TextChoices):
        EMPLOYEE = 'employee', 'Employee'
        EXTERNAL = 'external', 'External'

    class Meta:
        db_table = 'company_pad'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='pads')
    title = models.CharField(max_length=255)
    details = models.TextField()
    attachment = models.FileField(
        upload_to='company_pad/attachments/',
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=ATTACHMENT_EXTENSIONS)],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_pads'
    )

    party_b_type = models.CharField(max_length=10, choices=PartyBType.choices)
    party_b_employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='pads_to_sign'
    )
    party_b_name = models.CharField(max_length=255, null=True, blank=True)
    party_b_email = models.EmailField(null=True, blank=True)

    signed_by_admin_name = models.CharField(max_length=255, null=True, blank=True)
    signed_by_admin_at = models.DateTimeField(null=True, blank=True)
    signed_by_party_b_name = models.CharField(max_length=255, null=True, blank=True)
    signed_by_party_b_at = models.DateTimeField(null=True, blank=True)

    final_pdf = models.FileField(upload_to='company_pad/final/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def is_fully_signed(self):
        return self.status == self.Status.SIGNED

    def party_b_display_name(self):
        if self.party_b_type == self.PartyBType.EMPLOYEE and self.party_b_employee:
            return self.party_b_employee.get_full_name() or self.party_b_employee.username
        return self.party_b_name or '—'

    def save(self, *args, **kwargs):
        if self.pk:
            original = Pad.objects.filter(pk=self.pk).first()
            if original and original.status == self.Status.SIGNED:
                raise ValueError("A fully signed Company Pad cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.SIGNED:
            raise ValueError("A fully signed Company Pad cannot be deleted.")
        super().delete(*args, **kwargs)


def generate_token():
    return secrets.token_urlsafe(32)


class ShareLink(models.Model):
    pad = models.ForeignKey(Pad, on_delete=models.CASCADE, related_name='share_links')
    token = models.CharField(max_length=64, unique=True, default=generate_token, editable=False)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revoked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return not self.revoked and timezone.now() < self.expires_at

    def __str__(self):
        return f"{self.pad.title} — {self.token[:8]}…"