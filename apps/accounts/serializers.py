from django.contrib.auth import password_validation
from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import User


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.SerializerMethodField()
    role = serializers.CharField()
    role_display = serializers.CharField(source="get_role_display")
    must_change_password = serializers.BooleanField()

    def get_name(self, user) -> str:
        return user.get_full_name() or user.username


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Mot de passe actuel incorrect.")
        return value

    def validate(self, data):
        if data["new_password"] == data["current_password"]:
            raise serializers.ValidationError({"new_password": "Choisissez un mot de passe différent de l'actuel."})
        password_validation.validate_password(data["new_password"], self.context["request"].user)
        return data


# --- Gestion du personnel (gérant) ---

USERNAME = RegexValidator(r"^[a-z0-9._-]{3,30}$", "3 à 30 caractères : lettres minuscules sans accent, chiffres, point, tiret.")


class StaffMemberSerializer(serializers.ModelSerializer):
    """Compte du personnel vu par le gérant. Le mot de passe ne se lit jamais : il est seulement remis
    une fois, en clair, dans la réponse de création ou de réinitialisation (temporary_password)."""

    name = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    is_owner = serializers.BooleanField(source="is_superuser", read_only=True,
                                        help_text="Compte propriétaire (superutilisateur) : modifiable par lui seul.")
    username = serializers.CharField(max_length=30, help_text="Identifiant de connexion, mis en minuscules.")

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "name", "phone", "role", "role_display", "is_active",
                  "is_owner", "must_change_password", "last_login", "date_joined"]
        read_only_fields = ["must_change_password", "last_login", "date_joined"]

    def get_name(self, user) -> str:
        return user.get_full_name() or user.username

    def validate_username(self, value):
        value = value.strip().lower()
        USERNAME(value)  # après la mise en minuscules : « Fanta.Kone » devient « fanta.kone »
        taken = User.objects.filter(username__iexact=value)
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Cet identifiant est déjà pris.")
        return value

    def validate_first_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Indiquez le prénom.")
        return value.strip()


class StaffCreateSerializer(StaffMemberSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False,
                                     help_text="Facultatif : sans mot de passe, un mot de passe provisoire est généré.")

    class Meta(StaffMemberSerializer.Meta):
        fields = [*StaffMemberSerializer.Meta.fields, "password"]
        extra_kwargs = {"first_name": {"required": True}}

    def validate(self, data):
        if data.get("password"):
            probe = User(username=data["username"], first_name=data.get("first_name", ""), last_name=data.get("last_name", ""))
            password_validation.validate_password(data["password"], probe)
        return data


class StaffCredentialsSerializer(StaffMemberSerializer):
    """Réponse de création ou de réinitialisation : le compte et, une seule fois, son mot de passe provisoire."""

    temporary_password = serializers.CharField(read_only=True, allow_null=True,
                                               help_text="À transmettre à la personne ; il ne sera plus jamais affiché.")

    class Meta(StaffMemberSerializer.Meta):
        fields = [*StaffMemberSerializer.Meta.fields, "temporary_password"]
