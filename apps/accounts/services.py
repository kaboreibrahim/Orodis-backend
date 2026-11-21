"""Comptes du personnel : création, rôles, accès et mots de passe provisoires (écran « Personnel » du gérant)."""

import secrets

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from .models import User

# Sans 0/o, 1/l/i : le mot de passe se dicte ou se recopie sans erreur.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def temporary_password():
    """Trois groupes de trois caractères, par exemple « k7m-x3p-q9t » : 11 caractères, environ 45 bits."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(3)) for _ in range(3))


def end_sessions(user):
    """Met en liste noire tous les jetons de rafraîchissement du compte : ses sessions s'arrêtent
    au plus tard à l'expiration du jeton d'accès en cours (30 min), immédiatement s'il est désactivé."""
    for token in OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False):
        BlacklistedToken.objects.get_or_create(token=token)


def _check_can_edit(actor, member):
    if member.is_superuser and not actor.is_superuser:
        raise PermissionDenied("Le compte du propriétaire ne peut être modifié que par lui-même.")


def _other_active_managers(member):
    return User.objects.filter(is_active=True, role=User.Role.MANAGER).exclude(pk=member.pk).exists()


@transaction.atomic
def create_member(data):
    data = dict(data)
    password = data.pop("password", "") or None
    generated = None if password else temporary_password()
    member = User(**data, must_change_password=True)
    member.set_password(password or generated)
    member.save()
    return member, generated


@transaction.atomic
def update_member(actor, member, data):
    """Modifie un compte. Garde-fous : on ne se retire pas soi-même l'accès ou le rôle de gérant,
    et il reste toujours au moins un gérant actif."""
    _check_can_edit(actor, member)
    role = data.get("role", member.role)
    active = data.get("is_active", member.is_active)

    if member.pk == actor.pk:
        if not active:
            raise ValidationError({"is_active": ["Vous ne pouvez pas désactiver votre propre compte."]})
        if role != member.role:
            raise ValidationError({"role": ["Vous ne pouvez pas changer votre propre rôle : demandez à un autre gérant."]})
    leaves_managers = member.role == User.Role.MANAGER and member.is_active and (role != User.Role.MANAGER or not active)
    if leaves_managers and not _other_active_managers(member):
        raise ValidationError({"role": ["Il doit rester au moins un gérant actif."]})

    was_active = member.is_active
    for field, value in data.items():
        setattr(member, field, value)
    member.save()
    if was_active and not member.is_active:
        end_sessions(member)
    return member


@transaction.atomic
def reset_password(actor, member):
    """Nouveau mot de passe provisoire ; les sessions ouvertes du compte sont fermées."""
    _check_can_edit(actor, member)
    if member.pk == actor.pk:
        raise ValidationError({"detail": ["Pour votre propre compte, utilisez « Changer mon mot de passe »."]})
    password = temporary_password()
    member.set_password(password)
    member.must_change_password = True
    member.save(update_fields=["password", "must_change_password", "updated_at"])
    end_sessions(member)
    return password


def change_own_password(user, password):
    user.set_password(password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password", "updated_at"])
