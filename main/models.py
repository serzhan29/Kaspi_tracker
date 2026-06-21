from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
import hashlib


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Account(TimeStampedModel):
    class Currency(models.TextChoices):
        KZT = "KZT", "Тенге"
        USD = "USD", "Доллар"
        EUR = "EUR", "Евро"

    name = models.CharField(max_length=120)  # Kaspi Gold, Kaspi Deposit, Cash
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KZT)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Person(TimeStampedModel):
    class Kind(models.TextChoices):
        PERSON = "person", "Человек"
        COMPANY = "company", "Компания"
        SERVICE = "service", "Сервис"
        OTHER = "other", "Другое"
        FAMILY = "family", "Семья"
        SHOP = "shop", "Магазин"
        DEBTORS = "debtors", "Должники"

    name = models.CharField(max_length=150, unique=True)
    normalized_name = models.CharField(max_length=150, blank=True, db_index=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PERSON)
    note = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.normalized_name:
            self.normalized_name = self.name.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Люди или магазины"
        verbose_name_plural = "Люди или магазины"


class Category(TimeStampedModel):
    class Type(models.TextChoices):
        INCOME = "income", "Доход"
        EXPENSE = "expense", "Расход"
        TRANSFER = "transfer", "Перевод"
        DEBT = "debt", "Долг"
        SAVING = "saving", "Накопление"
        FEE = "fee", "Комиссия"
        OTHER = "other", "Другое"

    name = models.CharField(max_length=120, unique=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.EXPENSE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    color = models.CharField(max_length=20, blank=True)
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категорий"


class ImportBatch(TimeStampedModel):
    source_name = models.CharField(max_length=120, default="Kaspi PDF")
    file_name = models.CharField(max_length=255)
    file_hash = models.CharField(max_length=64, unique=True)  # sha256 файла
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)
    imported_rows = models.PositiveIntegerField(default=0)
    added_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    raw_file = models.FileField(upload_to="imports/", null=True, blank=True)

    def __str__(self):
        return f"{self.file_name} ({self.created_at:%Y-%m-%d})"


class Transaction(TimeStampedModel):
    class Source(models.TextChoices):
        KASPI_PDF = "kaspi_pdf", "Kaspi PDF"
        MANUAL = "manual", "Вручную"
        API = "api", "API"
        IMPORT = "import", "Импорт"

    class Kind(models.TextChoices):
        INCOME = "income", "Доход"
        EXPENSE = "expense", "Расход"
        TRANSFER_IN = "transfer_in", "Входящий перевод"
        TRANSFER_OUT = "transfer_out", "Исходящий перевод"
        DEPOSIT_IN = "deposit_in", "В депозит"
        DEPOSIT_OUT = "deposit_out", "Из депозита"
        LOAN_PAYMENT = "loan_payment", "Погашение кредита"
        CASH_WITHDRAWAL = "cash_withdrawal", "Снятие наличных"
        FEE = "fee", "Комиссия"
        ADJUSTMENT = "adjustment", "Корректировка"
        OTHER = "other", "Другое"

    batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transactions")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.KASPI_PDF)
    kind = models.CharField(max_length=30, choices=Kind.choices, default=Kind.OTHER)

    operation_date = models.DateField(db_index=True)
    operation_time = models.TimeField(null=True, blank=True)

    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default="KZT")

    description = models.CharField(max_length=255)          # YANDEX.EDA, Мерруерт Б., etc.
    raw_description = models.TextField(blank=True)          # полный текст из PDF
    operation_type = models.CharField(max_length=80, blank=True)  # Перевод, Покупка, Пополнение...
    direction = models.SmallIntegerField(default=-1)        # -1 расход, +1 доход, 0 нейтрально

    external_id = models.CharField(max_length=128, blank=True, null=True)
    fingerprint = models.CharField(max_length=64, unique=True)   # защита от дублей
    note = models.TextField(blank=True)

    is_manual = models.BooleanField(default=False)
    is_split = models.BooleanField(default=False)
    is_void = models.BooleanField(default=False)

    class Meta:
        ordering = ["-operation_date", "-id"]
        indexes = [
            models.Index(fields=["operation_date"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["source"]),
            models.Index(fields=["fingerprint"]),
        ]
        verbose_name = "Транзакций"
        verbose_name_plural = "Транзакций"

    def save(self, *args, **kwargs):
        if not self.fingerprint:
            base = f"{self.operation_date}|{self.amount}|{self.operation_type}|{self.description}|{self.account_id}|{self.source}"
            self.fingerprint = hashlib.sha256(base.encode("utf-8")).hexdigest()

        if self.kind in {self.Kind.INCOME, self.Kind.TRANSFER_IN, self.Kind.DEPOSIT_IN}:
            self.direction = 1
        elif self.kind in {self.Kind.EXPENSE, self.Kind.TRANSFER_OUT, self.Kind.DEPOSIT_OUT, self.Kind.LOAN_PAYMENT, self.Kind.CASH_WITHDRAWAL, self.Kind.FEE}:
            self.direction = -1
        else:
            self.direction = 0

        super().save(*args, **kwargs)

    def __str__(self):
        sign = "+" if self.direction == 1 else "-"
        return f"{self.operation_date} {sign}{self.amount} {self.description}"


class DebtEntry(TimeStampedModel):
    """
    Отдельный учёт долгов/взаиморасчётов.
    Можно использовать, если хочешь видеть: кто кому должен.
    """
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="debt_entries")
    transaction = models.ForeignKey(Transaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="debt_entries")

    class Side(models.TextChoices):
        YOU_LENT = "you_lent", "Ты дал"
        THEY_REPAID = "they_repaid", "Тебе вернули"
        YOU_RETURNED = "you_returned", "Ты вернул"
        THEY_PAID = "they_paid", "Они заплатили"
        ADJUSTMENT = "adjustment", "Корректировка"

    side = models.CharField(max_length=20, choices=Side.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.person}: {self.side} {self.amount}"


class TransactionTag(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


class TransactionTagLink(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    tag = models.ForeignKey(TransactionTag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("transaction", "tag")