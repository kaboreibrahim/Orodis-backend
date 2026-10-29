from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models

from apps.core.models import TimeStampedModel


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", self.model.Role.MANAGER)
        return super().create_superuser(username, email, password, **extra_fields)


class User(TimeStampedModel, AbstractUser):
    class Role(models.TextChoices):
        MANAGER = "manager", "Gérant"
        CASHIER = "cashier", "Caisse"
        WAITER = "waiter", "Serveur"
        KITCHEN = "kitchen", "Cuisine"

    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.WAITER)
    phone = models.CharField("téléphone", max_length=20, blank=True)

    objects = UserManager()

    class Meta:
        verbose_name = "membre du personnel"
        verbose_name_plural = "membres du personnel"

    def __str__(self):
        return self.get_full_name() or self.username
