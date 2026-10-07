"""Build an offline city -> (lat, lon) lookup from the GeoNames US gazetteer.

Run once (or whenever the station CSV changes). The resulting JSON is committed
to the repo so that ``load_stations`` -- and therefore every API request -- needs
no geocoding network calls at all.

    python manage.py build_geo_cache

GeoNames "US.txt" is a tab-separated dump of every US populated place with
latitude/longitude and the 2-letter state code in the admin1 column, which is
exactly what we need to place each truck-stop (we only have city + state).
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

GEONAMES_US_URL = "https://download.geonames.org/export/dump/US.zip"

# Column indices in the GeoNames dump (see the readme at the URL above).
COL_NAME = 1
COL_ASCIINAME = 2
COL_ALTNAMES = 3
COL_LAT = 4
COL_LON = 5
COL_FEATURE_CLASS = 6
COL_COUNTRY = 8
COL_ADMIN1 = 10
COL_POPULATION = 14


def _norm(name: str) -> str:
    return name.strip().upper()


class Command(BaseCommand):
    help = "Download the GeoNames US gazetteer and build a city->coords JSON cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            help="Path to a pre-downloaded US.txt or US.zip (skips the download).",
        )
        parser.add_argument(
            "--csv",
            default=str(settings.BASE_DIR / "fuel-prices-for-be-assessment.csv"),
            help="Station CSV; only the (city, state) pairs it contains are kept.",
        )
        parser.add_argument(
            "--out",
            default=str(settings.GEO_CACHE_PATH),
            help="Where to write the JSON cache.",
        )

    def handle(self, *args, **options):
        needed = self._needed_cities(options["csv"])
        self.stdout.write(f"CSV references {len(needed)} unique (city, state) pairs.")

        lines = self._read_geonames(options.get("source"))

        # key "CITY|STATE" -> (lat, lon, population). Higher population wins ties.
        primary: dict[str, tuple[float, float, int]] = {}
        alternate: dict[str, tuple[float, float, int]] = {}

        for row in lines:
            if len(row) <= COL_POPULATION:
                continue
            if row[COL_FEATURE_CLASS] != "P" or row[COL_COUNTRY] != "US":
                continue
            state = _norm(row[COL_ADMIN1])
            try:
                lat = float(row[COL_LAT])
                lon = float(row[COL_LON])
                pop = int(row[COL_POPULATION] or 0)
            except ValueError:
                continue

            names = {_norm(row[COL_NAME]), _norm(row[COL_ASCIINAME])}
            for name in names:
                key = f"{name}|{state}"
                if key not in needed:
                    continue
                cur = primary.get(key)
                if cur is None or pop > cur[2]:
                    primary[key] = (lat, lon, pop)

            # Alternate names are lower priority; only used to fill gaps.
            for alt in row[COL_ALTNAMES].split(","):
                alt = _norm(alt)
                key = f"{alt}|{state}"
                if key not in needed:
                    continue
                cur = alternate.get(key)
                if cur is None or pop > cur[2]:
                    alternate[key] = (lat, lon, pop)

        cache: dict[str, list[float]] = {}
        for key in needed:
            hit = primary.get(key) or alternate.get(key)
            if hit:
                cache[key] = [round(hit[0], 6), round(hit[1], 6)]

        out_path = Path(options["out"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(cache, sort_keys=True, indent=0))

        matched = len(cache)
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {matched}/{len(needed)} city coords to {out_path} "
                f"({matched / max(len(needed), 1):.0%} coverage)."
            )
        )
        missing = sorted(k for k in needed if k not in cache)
        if missing:
            self.stdout.write(
                f"Unmatched (left without coords): {', '.join(missing[:20])}"
                + (" ..." if len(missing) > 20 else "")
            )

    def _needed_cities(self, csv_path: str) -> set[str]:
        needed: set[str] = set()
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                needed.add(f"{_norm(row['City'])}|{_norm(row['State'])}")
        return needed

    def _read_geonames(self, source: str | None):
        """Yield split rows from the GeoNames dump (download or local file)."""
        if source and source.endswith(".txt"):
            self.stdout.write(f"Reading GeoNames from {source} ...")
            with open(source, encoding="utf-8") as fh:
                for line in fh:
                    yield line.rstrip("\n").split("\t")
            return

        if source and source.endswith(".zip"):
            self.stdout.write(f"Reading GeoNames from {source} ...")
            data = Path(source).read_bytes()
        else:
            self.stdout.write(f"Downloading GeoNames gazetteer: {GEONAMES_US_URL}")
            resp = requests.get(
                GEONAMES_US_URL,
                timeout=settings.HTTP_TIMEOUT_SECONDS * 10,
                headers={"User-Agent": settings.HTTP_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.content

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with zf.open("US.txt") as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8")
                for line in text:
                    yield line.rstrip("\n").split("\t")
