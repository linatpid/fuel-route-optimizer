from django.db import models


class FuelStation(models.Model):
    """A truck-stop / fuel station loaded from the assessment CSV.

    Coordinates are filled in at load time by geocoding the station's
    city + state against an offline GeoNames gazetteer, so that serving a
    request never has to geocode ~8k stations on the fly.
    """

    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=8, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5)

    # Populated during load. null => could not be geocoded (excluded from routing).
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            # Bounding-box prefilter when selecting stations near a route.
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.retail_price}"
