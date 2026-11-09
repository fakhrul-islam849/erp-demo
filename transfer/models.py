from django.db import models


class Transfer(models.Model):
    class Status(models.TextChoices):
        IN_TRANSIT = 'in_transit', 'In transit'
        CONFIRMED = 'confirmed', 'Confirmed'
        CANCELLED = 'cancelled', 'Cancelled'

    from_warehouse = models.ForeignKey('warehouse.Warehouse', on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey('warehouse.Warehouse', on_delete=models.PROTECT, related_name='transfers_in')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_TRANSIT)
    note = models.TextField(blank=True)

    # only needed when the transfer has a net cost (packing, delivery, tax...)
    account = models.ForeignKey(
        'payment_account.Account',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transfers',
    )
    transaction = models.OneToOneField(
        'payment_account.Transaction',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transfer',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    # computed by the transfer service; never entered by the user
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'transfer'
        ordering = ['-date', '-id']
        constraints = [
            models.CheckConstraint(
                check=~models.Q(from_warehouse=models.F('to_warehouse')),
                name='transfer_warehouses_differ',
            ),
        ]

    @property
    def net_cost(self):
        return self.total_cost - self.total_discount

    def __str__(self):
        return f'Transfer #{self.pk}'
