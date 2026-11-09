from django.db import models


class SaleAdjustmentType(models.Model):
    class Type(models.TextChoices):
        ADD = 'add', 'Add (charge to customer)'
        DEDUCT = 'deduct', 'Deduct (discount)'

    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=10, choices=Type.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale_adjustment_type'

    def __str__(self):
        return self.name


class Sale(models.Model):
    class Status(models.TextChoices):
        SOLD = 'sold', 'Sold'
        RETURNED = 'returned', 'Returned'
        DAMAGED = 'damaged', 'Damaged'

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RECEIVED = 'received', 'Received'
        REFUND = 'refund', 'Refund'

    account = models.ForeignKey('payment_account.Account', on_delete=models.PROTECT, related_name='sales')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SOLD)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    details = models.TextField(blank=True)

    # computed by the sale service; never entered by the user
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)  # sum of line totals
    lines_add = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    lines_deduct = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_add = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_deduct = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sale',
    )
    # money paid back to the customer; the original transaction stays as the record
    refund_transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='refunded_sale',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'Sale #{self.pk}'


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='lines')
    lot = models.ForeignKey('purchase.StockLot', on_delete=models.PROTECT, related_name='sale_lines')
    quantity = models.PositiveIntegerField()
    # copied from lot.sale_price when the sale is saved; never edited by the user
    sale_price = models.DecimalField(max_digits=14, decimal_places=2)

    # computed by the sale service
    add_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deduct_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale_line'
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name='sale_line_quantity_positive'),
            models.CheckConstraint(check=models.Q(sale_price__gte=0), name='sale_line_price_non_negative'),
        ]

    def __str__(self):
        return f'{self.lot.product} x {self.quantity}'


class SaleAdjustment(models.Model):
    """Fixed amount added to or deducted from the sale; line is NULL when it covers the whole sale."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='adjustments')
    line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, null=True, blank=True, related_name='adjustments')
    adjustment_type = models.ForeignKey(SaleAdjustmentType, on_delete=models.PROTECT, related_name='adjustments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sale_adjustment'
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='sale_adjustment_amount_positive'),
        ]

    def __str__(self):
        return f'{self.adjustment_type} {self.amount}'
