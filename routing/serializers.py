from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    """Validates the start/finish inputs.

    Both accept either a free-text US place ("Chicago, IL", "New York, NY")
    or raw ``"lat,lon"`` coordinates.
    """

    start = serializers.CharField(max_length=255)
    finish = serializers.CharField(max_length=255)

    def validate_start(self, value):
        return value.strip()

    def validate_finish(self, value):
        return value.strip()
