"""External data: NASA FIRMS fires, Open-Meteo wind, Open-Meteo air-quality (CAMS) baseline.

Fetchers return raw text/JSON (so the ingest Lambda can snapshot them to S3 for back-testing);
parsers turn that into model inputs and are pure functions.
"""
import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .cities import FIRE_BBOX, grid_points
from .model import WindField, ventilation_stats

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/{days}"
WIND_URL = "https://api.open-meteo.com/v1/forecast"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT_S = 25


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "smoke-shield/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read().decode("utf-8")


# ---- fires ---------------------------------------------------------------------------------

FIRE_WINDOW_HOURS = 24      # the model is built on "fires burning in the last 24 h"
FUTURE_SKEW = timedelta(minutes=30)


def fetch_fires_csv(map_key, day_range=2):
    """FIRMS VIIRS (375 m) near-real-time detections. Free MAP_KEY: https://firms.modaps.eosdis.nasa.gov/api/map_key/

    day_range counts UTC *calendar days*, so 1 means "today since 00:00 UTC", not "the last 24 hours". The satellite passes over
    India around 08:00 UTC and its data lands a few hours later, so day_range=1 returned nothing from midnight until ~10:00 UTC
    (05:30-15:30 IST, the whole school morning). Ask for 2 days and let parse_fires(now=...) keep exactly the last 24 hours.
    """
    if not map_key:
        raise RuntimeError("FIRMS_MAP_KEY is not set")
    bbox = ",".join(str(x) for x in FIRE_BBOX)
    return _get(FIRMS_URL.format(key=map_key, bbox=bbox, days=day_range))


def _acquired(row):
    """UTC acquisition time of a FIRMS row, or None if the date/time columns are missing or malformed."""
    try:
        hhmm = str(row["acq_time"]).strip().zfill(4)          # FIRMS writes 0812, but be tolerant of 812
        return datetime.strptime(f"{row['acq_date'].strip()} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, AttributeError):
        return None


def parse_fires(csv_text, now=None, max_age_hours=FIRE_WINDOW_HOURS):
    """-> [{'lat','lon','frp'}]; drops low-confidence detections (VIIRS confidence: l / n / h).

    With `now`, also drops detections older than `max_age_hours` (and any dated in the future). Rows with no usable
    acquisition time are kept, because we cannot tell how old they are.
    """
    out = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            if str(row.get("confidence", "")).strip().lower().startswith("l"):
                continue
            if now is not None:
                t = _acquired(row)
                if t is not None and not (now - timedelta(hours=max_age_hours) <= t <= now + FUTURE_SKEW):
                    continue
            out.append({"lat": float(row["latitude"]), "lon": float(row["longitude"]),
                        "frp": float(row.get("frp") or 0.0)})
        except (KeyError, ValueError):
            continue  # an error body or malformed row must not crash the run
    return out


# ---- wind ----------------------------------------------------------------------------------

def _multi(points):
    return (",".join(str(p[0]) for p in points), ",".join(str(p[1]) for p in points))


def fetch_wind_json(points=None):
    points = points or grid_points()
    lats, lons = _multi(points)
    qs = urllib.parse.urlencode({
        "latitude": lats, "longitude": lons,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kmh", "forecast_days": 3, "timezone": "UTC",
    })
    return json.loads(_get(f"{WIND_URL}?{qs}"))


def _as_list(payload):
    return payload if isinstance(payload, list) else [payload]


def _start_index(times, now):
    """Index of the hour containing `now` in an Open-Meteo UTC hourly time list."""
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    for i, t in enumerate(times):
        if t >= stamp:
            return i
    return 0


def parse_wind(payload, now, points=None):
    points = points or grid_points()
    field = {}
    for pt, loc in zip(points, _as_list(payload)):
        h = loc["hourly"]
        i = _start_index(h["time"], now)
        speeds, dirs = h["wind_speed_10m"][i:], h["wind_direction_10m"][i:]
        series = [(s, d) for s, d in zip(speeds, dirs) if s is not None and d is not None]
        if series:
            field[pt] = series
    return WindField(field)


def synthetic_wind(from_deg=315.0, speed_kmh=15.0, hours=72):
    """Uniform wind for tests / offline demos. 315 = north-westerly, the classic Oct-Nov pattern."""
    return WindField({pt: [(speed_kmh, from_deg)] * hours for pt in grid_points()})


# ---- air-quality baseline ------------------------------------------------------------------

def fetch_aq_json(cities):
    pts = [(c["lat"], c["lon"]) for c in cities.values()]
    lats, lons = _multi(pts)
    qs = urllib.parse.urlencode({
        "latitude": lats, "longitude": lons,
        "hourly": "pm2_5", "forecast_days": 2, "timezone": "UTC",
    })
    return json.loads(_get(f"{AQ_URL}?{qs}"))


def parse_aq(payload, cities, now):
    """-> {city_key: {'pm25_now', 'pm25_max_24h'}}. CAMS is coarse over India and tends to read low."""
    out = {}
    for key, loc in zip(cities, _as_list(payload)):
        h = loc["hourly"]
        i = _start_index(h["time"], now)
        vals = [v for v in h["pm2_5"][i:i + 24] if v is not None]
        out[key] = {"pm25_now": vals[0] if vals else None,
                    "pm25_max_24h": max(vals) if vals else None}
    return out


# ---- meteorology for the ventilation term ----------------------------------------------------

def fetch_met_json(cities):
    """Hourly boundary-layer height and 10 m wind (m/s) at each city, 3-day forecast."""
    lats, lons = _multi([(c["lat"], c["lon"]) for c in cities.values()])
    qs = urllib.parse.urlencode({
        "latitude": lats, "longitude": lons, "hourly": "boundary_layer_height,wind_speed_10m",
        "wind_speed_unit": "ms", "forecast_days": 3, "timezone": "UTC",
    })
    return json.loads(_get(f"{WIND_URL}?{qs}"))


def parse_ventilation(payload, cities, now, hours=48):
    """-> {city_key: ventilation_stats} over the next `hours`; cities without enough data are omitted."""
    out = {}
    for key, loc in zip(cities, _as_list(payload)):
        h = loc["hourly"]
        i = _start_index(h["time"], now)
        stats = ventilation_stats(h["boundary_layer_height"][i:i + hours], h["wind_speed_10m"][i:i + hours])
        if stats:
            out[key] = stats
    return out


def utcnow():
    return datetime.now(timezone.utc)
