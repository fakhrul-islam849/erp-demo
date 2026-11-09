from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models

ATTACHMENT_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']
MAX_ATTACHMENT_MB = 5
MAX_ATTACHMENT_BYTES = MAX_ATTACHMENT_MB * 1024 * 1024


def validate_attachment_size(file):
    if file.size > MAX_ATTACHMENT_BYTES:
        raise ValidationError(f'The attachment is too large; the limit is {MAX_ATTACHMENT_MB} MB.')


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expense_category'
        ordering = ['name']
        verbose_name_plural = 'expense categories'

    def __str__(self):
        return self.name


class Expense(models.Model):
    title = models.CharField(max_length=255)
    account = models.ForeignKey('payment_account.Account', on_delete=models.PROTECT, related_name='expenses')
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    attachment = models.FileField(
        upload_to='expense/attachments/',
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=ATTACHMENT_EXTENSIONS), validate_attachment_size],
    )

    # the paid 'expense' transaction that takes the amount out of the account
    transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='expense',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expense'
        ordering = ['-date', '-id']
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='expense_amount_positive'),
        ]

    def __str__(self):
        return self.title
