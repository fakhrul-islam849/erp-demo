from django.db import models


class Warehouse(models.Model):
    name = models.CharField(max_length=255)
    marketplace_name = models.CharField(max_length=255)
    marketplace_location = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'warehouse'

    def __str__(self):
        return self.name