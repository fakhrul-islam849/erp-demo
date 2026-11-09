from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models

INVOICE_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']


class PurchaseAdjustmentType(models.Model):
    class Type(models.TextChoices):
        ADD = 'add', 'Add (cost)'
        DEDUCT = 'deduct', 'Deduct (discount)'

    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=10, choices=Type.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_adjustment_type'

    def __str__(self):
        return self.name


class Purchase(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'

    warehouse = models.ForeignKey('warehouse.Warehouse', on_delete=models.PROTECT, related_name='purchases')
    supplier = models.ForeignKey('supplier.Supplier', on_delete=models.PROTECT, related_name='purchases')
    account = models.ForeignKey('payment_account.Account', on_delete=models.PROTECT, related_name='purchases')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    invoice = models.FileField(
        upload_to='purchase/invoices/',
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=INVOICE_EXTENSIONS)],
    )
    note = models.TextField(blank=True)

    # computed by recalculate_purchase(); never entered by the user
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='purchase',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase'
        ordering = ['-date', '-id']

    def __str__(self):
        return f'Purchase #{self.pk}'


class StockLotQuerySet(models.QuerySet):
    def in_warehouse(self, warehouse):
        return self.filter(
            models.Q(purchase__warehouse=warehouse) | models.Q(transfer__to_warehouse=warehouse)
        )

    def available(self, warehouse=None):
        """Lots that can be sold or transferred right now.

        Stock from a cancelled purchase or from a transfer that has not been
        confirmed yet does not count.
        """
        lots = self.filter(remaining_quantity__gt=0).filter(
            models.Q(purchase__isnull=False) & ~models.Q(purchase__status=Purchase.Status.CANCELLED)
            | models.Q(transfer__status='confirmed')
        )
        return lots.in_warehouse(warehouse) if warehouse is not None else lots


class StockLot(models.Model):
    """One batch of a product in one warehouse, from a purchase or a transfer."""

    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, null=True, blank=True, related_name='lots',
    )
    transfer = models.ForeignKey(
        'transfer.Transfer', on_delete=models.CASCADE, null=True, blank=True, related_name='lots',
    )
    # the lot a transfer lot was moved out of
    source_lot = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='transferred_lots',
    )
    product = models.ForeignKey('product.Product', on_delete=models.PROTECT, related_name='stock_lots')
    quantity = models.PositiveIntegerField()
    remaining_quantity = models.PositiveIntegerField()

    purchase_price = models.DecimalField(max_digits=16, decimal_places=4)
    sale_price = models.DecimalField(max_digits=14, decimal_places=2)

    # computed by recalculate_purchase(); never entered by the user
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    landed_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StockLotQuerySet.as_manager()

    class Meta:
        db_table = 'stock_lot'
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(purchase__isnull=False, transfer__isnull=True)
                    | models.Q(purchase__isnull=True, transfer__isnull=False)
                ),
                name='stock_lot_exactly_one_owner',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(transfer__isnull=True, source_lot__isnull=True)
                    | models.Q(transfer__isnull=False, source_lot__isnull=False)
                ),
                name='stock_lot_source_only_on_transfer',
            ),
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name='stock_lot_quantity_positive',
            ),
            models.CheckConstraint(
                check=models.Q(remaining_quantity__lte=models.F('quantity')),
                name='stock_lot_remaining_lte_quantity',
            ),
            models.CheckConstraint(
                check=models.Q(purchase_price__gte=0) & models.Q(sale_price__gte=0),
                name='stock_lot_prices_non_negative',
            ),
        ]

    @property
    def warehouse(self):
        owner = self.purchase if self.purchase_id else self.transfer
        return owner.warehouse if self.purchase_id else owner.to_warehouse

    def __str__(self):
        return f'{self.product} x {self.quantity}'


class PurchaseAdjustment(models.Model):
    """Belongs to a purchase or a transfer; lot is NULL when it covers the whole of it."""

    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, null=True, blank=True, related_name='adjustments',
    )
    transfer = models.ForeignKey(
        'transfer.Transfer', on_delete=models.CASCADE, null=True, blank=True, related_name='adjustments',
    )
    lot = models.ForeignKey(
        StockLot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='adjustments',
    )
    adjustment_type = models.ForeignKey(
        PurchaseAdjustmentType,
        on_delete=models.PROTECT,
        related_name='adjustments',
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_adjustment'
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='purchase_adjustment_amount_positive',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(purchase__isnull=False, transfer__isnull=True)
                    | models.Q(purchase__isnull=True, transfer__isnull=False)
                ),
                name='purchase_adjustment_exactly_one_owner',
            ),
        ]

    @property
    def scope(self):
        return 'line' if self.lot_id else 'purchase'

    def clean(self):
        if self.lot_id and (
            self.lot.purchase_id != self.purchase_id or self.lot.transfer_id != self.transfer_id
        ):
            raise ValidationError('The line must belong to the same purchase or transfer.')

    def __str__(self):
        return f'{self.adjustment_type} {self.amount}'
