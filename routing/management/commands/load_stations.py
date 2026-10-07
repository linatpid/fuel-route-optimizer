"""Load the fuel-price CSV into the database, attaching coordinates.

    python manage.py load_stations

Coordinates come from the committed GeoNames cache (see ``build_geo_cache``),
so this runs fully offline and takes a second or two for the whole file.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routing.models import FuelStation


def _norm(value: str) -> str:
    return value.strip().upper()


class Command(BaseCommand):
    help = "Load the fuel-price CSV into the FuelStation table with coordinates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=str(settings.BASE_DIR / "fuel-prices-for-be-assessment.csv"),
        )
        parser.add_argument("--cache", default=str(settings.GEO_CACHE_PATH))

    def handle(self, *args, **options):
        cache_path = options["cache"]
        try:
            coords = json.loads(open(cache_path, encoding="utf-8").read())
        except FileNotFoundError:
            raise CommandError(
                f"Coordinate cache not found at {cache_path}. "
                "Run `python manage.py build_geo_cache` first."
            )

        stations: list[FuelStation] = []
        geocoded = 0
        with open(options["csv"], newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    price = Decimal(row["Retail Price"])
                except (InvalidOperation, KeyError):
                    continue

                city, state = row["City"].strip(), row["State"].strip()
                latlon = coords.get(f"{_norm(city)}|{_norm(state)}")
                lat, lon = (latlon[0], latlon[1]) if latlon else (None, None)
                if latlon:
                    geocoded += 1

                stations.append(
                    FuelStation(
                        opis_id=int(row["OPIS Truckstop ID"]),
                        name=row["Truckstop Name"].strip(),
                        address=row["Address"].strip(),
                        city=city,
                        state=state,
                        rack_id=int(row["Rack ID"]) if row.get("Rack ID") else None,
                        retail_price=price,
                        latitude=lat,
                        longitude=lon,
                    )
                )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)

        total = len(stations)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {total} stations; {geocoded} geocoded "
                f"({geocoded / max(total, 1):.0%}), "
                f"{total - geocoded} without coordinates (skipped in routing)."
            )
        )
