from django.db import models


class IncomeCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'income_category'
        ordering = ['name']
        verbose_name_plural = 'income categories'

    def __str__(self):
        return self.name


class Income(models.Model):
    title = models.CharField(max_length=255)
    account = models.ForeignKey('payment_account.Account', on_delete=models.PROTECT, related_name='incomes')
    category = models.ForeignKey(IncomeCategory, on_delete=models.PROTECT, related_name='incomes')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()

    # the received 'income' transaction that puts the amount in the account
    transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='income',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'income'
        ordering = ['-date', '-id']
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='income_amount_positive'),
        ]

    def __str__(self):
        return self.title
