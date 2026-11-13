from rest_framework import serializers


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.SerializerMethodField()
    role = serializers.CharField()
    role_display = serializers.CharField(source="get_role_display")

    def get_name(self, user) -> str:
        return user.get_full_name() or user.username


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
