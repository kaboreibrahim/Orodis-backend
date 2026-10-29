from rest_framework.permissions import BasePermission

STAFF_ROLES = ("manager", "cashier", "waiter", "kitchen")


def _has_role(user, roles):
    return bool(user and user.is_authenticated and user.is_active and (user.is_superuser or user.role in roles))


class IsStaffRole(BasePermission):
    message = "Accès réservé au personnel."

    def has_permission(self, request, view):
        return _has_role(request.user, STAFF_ROLES)


class IsManager(BasePermission):
    message = "Accès réservé au gérant."

    def has_permission(self, request, view):
        return _has_role(request.user, ("manager",))


def HasRole(*roles):
    """Usage : permission_classes = [HasRole("cashier", "manager")]"""

    class _HasRole(BasePermission):
        message = "Votre rôle ne permet pas cette action."

        def has_permission(self, request, view):
            return _has_role(request.user, roles)

    _HasRole.__name__ = f"HasRole({', '.join(roles)})"
    return _HasRole
