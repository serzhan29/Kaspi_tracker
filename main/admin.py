# finance/admin.py

from django.contrib import admin
from .models import *


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "kind")
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "type")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "operation_date",
        "amount",
        "description",
        "kind",
        "person",
    )

    search_fields = (
        "description",
    )

    list_filter = (
        "kind",
        "category",
    )