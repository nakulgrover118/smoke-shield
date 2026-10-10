"""Deterministic smoke-arrival model. No I/O, no AWS - everything here is unit-testable.

Idea: bin active fires into cells, release one air parcel per cell *now*, push each parcel
along the hourly forecast wind for up to HORIZON_H hours, and record the hour it first
passes within ARRIVAL_RADIUS_KM of a city. Each cell contributes its fire radiative power
(FRP, MW), discounted by travel time (dilution/deposition). The sum is the city's smoke load.

Known simplifications (state these honestly in the demo):
  * 10 m wind on a coarse grid; real transport happens through the boundary layer.
  * One release time. Fires keep burning, so exposure persists longer than the window shows.
  * No plume spread, no chemistry, no deposition model - just an exponential discount.
All CALIBRATE constants should be tuned against the back-test (scripts/backtest.py).
"""
import math
from dataclasses import dataclass

from .geo import advance, haversine_km, travel_bearing

HORIZON_H = 48
ARRIVAL_RADIUS_KM = 50.0      # CALIBRATE
DECAY_H = 24.0                # CALIBRATE: e-folding time of smoke contribution
WIND_SCALE = 1.0              # CALIBRATE: 10 m wind underestimates mixed-layer transport
CELL_DEG = 0.25               # fire binning resolution (~25 km)

LEVELS = ["LOW", "MODERATE", "HIGH", "SEVERE"]
# CALIBRATE: smoke_load (MW, travel-time weighted) lower bounds for MODERATE / HIGH / SEVERE
LOAD_THRESHOLDS = (100.0, 500.0, 2000.0)
BAD_BASELINE_PM25 = 250.0     # forecast PM2.5 (ug/m3) already bad -> bump one level


VI_FLOOR = 100.0              # CALIBRATE: m2/s. Stops 1/VI exploding on windless nights with a ~50 m boundary layer.
SMOKE_INDEX_SCALE = 1000.0    # only makes smoke_index a readable number; rankings don't depend on it


def ventilation_stats(blh_m, wind_ms, floor=VI_FLOOR, min_hours=24):
    """Ventilation index VI = boundary-layer height (m) x wind speed (m/s), in m2/s: how fast the air mixes smoke away.

    Concentration scales ~1/VI, so exposure over a window is the mean of 1/VI, not 1/mean(VI): one stagnant night matters.
    Returns None unless at least `min_hours` hours have both inputs.
    """
    vis = [b * w for b, w in zip(blh_m, wind_ms) if b is not None and w is not None]
    if len(vis) < min_hours:
        return None
    inv = sum(1.0 / max(v, floor) for v in vis) / len(vis)
    return {"vi_mean": round(sum(vis) / len(vis), 1), "vi_min": round(min(vis), 1),
            "vi_eff": round(1.0 / inv, 1), "inv_vi": inv}


# Air-mixing label, from the effective 48 h ventilation 1 / mean(1/VI) in m2/s. Cut-offs are the pooled 30th / 70th percentile
# of Oct 20 - Nov 25 in 2017-2019 (leave-one-season-out values were 156-168 and 221-244). In those held-out seasons, for Delhi and
# Gurugram, mean PM2.5 was ~249 / 192 / 175 ug/m3 for POOR / MODERATE / GOOD (days >= 150: 94% / 76% / 59%).
# CALIBRATE: derived from ERA5 reanalysis, which can differ from live forecast boundary-layer heights; revisit with real snapshots.
STAGNATION_POOR_BELOW = 165.0
STAGNATION_GOOD_FROM = 240.0


def stagnation_label(ventilation):
    """'POOR' | 'MODERATE' | 'GOOD' air mixing over the next 48 h, or None without meteorology."""
    if not ventilation:
        return None
    eff = round(1.0 / ventilation["inv_vi"], 1)   # same rounding as the reported vi_eff, and immune to 1/(1/x) float error at a cut-off
    return "POOR" if eff < STAGNATION_POOR_BELOW else ("GOOD" if eff >= STAGNATION_GOOD_FROM else "MODERATE")


def smoke_index(load, ventilation):
    """Smoke load divided by ventilation: a concentration-like index. None without meteorology."""
    if not ventilation:
        return None
    return round(load * ventilation["inv_vi"] * SMOKE_INDEX_SCALE, 2)


@dataclass(frozen=True)
class ModelParams:
    """The three physical knobs scripts/backtest.py tunes. Defaults are the module constants above."""
    radius_km: float = ARRIVAL_RADIUS_KM
    decay_h: float = DECAY_H
    wind_scale: float = WIND_SCALE


DEFAULT_PARAMS = ModelParams()


@dataclass(frozen=True)
class FireCell:
    lat: float
    lon: float
    frp: float      # summed fire radiative power, MW
    count: int


class WindField:
    """Hourly wind on a lat/lon point grid. Index 0 = the current hour."""

    def __init__(self, points):
        # points: {(lat, lon): [(speed_kmh, from_deg), ...]}
        if not points:
            raise ValueError("empty wind field")
        self.points = points

    def at(self, lat, lon, hour):
        # Called ~cells x 48 times per run, so use a cheap equirectangular distance, not haversine.
        k = math.cos(math.radians(lat))
        key = min(self.points, key=lambda p: (p[0] - lat) ** 2 + ((p[1] - lon) * k) ** 2)
        series = self.points[key]
        return series[min(max(hour, 0), len(series) - 1)]


def cluster_fires(fires, cell_deg=CELL_DEG):
    """fires: iterable of {'lat','lon','frp'} -> list[FireCell], one per occupied grid cell."""
    bins = {}
    for f in fires:
        k = (math.floor(f["lat"] / cell_deg), math.floor(f["lon"] / cell_deg))
        b = bins.setdefault(k, {"lat": 0.0, "lon": 0.0, "frp": 0.0, "n": 0})
        b["lat"] += f["lat"]
        b["lon"] += f["lon"]
        b["frp"] += max(float(f.get("frp") or 0.0), 0.0)
        b["n"] += 1
    return [FireCell(b["lat"] / b["n"], b["lon"] / b["n"], b["frp"], b["n"]) for b in bins.values()]


def forward_trajectory(cell, wind, hours=HORIZON_H, params=DEFAULT_PARAMS):
    """Positions of a parcel released at the fire cell, one per hour (hour 1..hours)."""
    lat, lon = cell.lat, cell.lon
    path = []
    for h in range(hours):
        speed, from_deg = wind.at(lat, lon, h)
        lat, lon = advance(lat, lon, travel_bearing(from_deg), speed * params.wind_scale)
        path.append((lat, lon))
    return path


def compute_paths(cells, wind, params=DEFAULT_PARAMS):
    """One trajectory per fire cell. Paths don't depend on the city, so compute them once and share."""
    return [forward_trajectory(c, wind, params=params) for c in cells]


def arrival_hour(path, city_lat, city_lon, radius_km=ARRIVAL_RADIUS_KM, origin=None):
    """First hour (1-based) the parcel is within radius of the city, else None.

    If the fire itself (`origin`) is already inside the radius the smoke is local: report hour 1.
    """
    if origin is not None and haversine_km(origin[0], origin[1], city_lat, city_lon) <= radius_km:
        return 1
    for i, (lat, lon) in enumerate(path):
        if haversine_km(lat, lon, city_lat, city_lon) <= radius_km:
            return i + 1
    return None


def _quantile(sorted_pairs, q):
    """Weighted quantile over [(value, weight)] sorted by value."""
    total = sum(w for _, w in sorted_pairs)
    acc = 0.0
    for v, w in sorted_pairs:
        acc += w
        if acc >= q * total:
            return v
    return sorted_pairs[-1][0]


def risk_level(smoke_load, pm25_max_24h=None, thresholds=LOAD_THRESHOLDS):
    idx = sum(smoke_load >= t for t in thresholds)
    if pm25_max_24h is not None and pm25_max_24h >= BAD_BASELINE_PM25 and smoke_load >= thresholds[0]:
        idx = min(idx + 1, len(LEVELS) - 1)
    return LEVELS[idx]


def assess_city(city, cells, wind, pm25_now=None, pm25_max_24h=None, *,
                params=DEFAULT_PARAMS, paths=None, thresholds=LOAD_THRESHOLDS, ventilation=None):
    """Return a plain-dict risk record for one city. Hours are relative to 'now'.

    Pass `paths=compute_paths(...)` when assessing several cities against the same fires and wind.
    `ventilation` (from ventilation_stats) adds context fields only; it does not change risk_level yet.
    """
    if paths is None:
        paths = compute_paths(cells, wind, params)
    hits = []
    for cell, path in zip(cells, paths):
        h = arrival_hour(path, city["lat"], city["lon"], params.radius_km, origin=(cell.lat, cell.lon))
        if h is not None:
            hits.append((h, cell, cell.frp * math.exp(-h / params.decay_h)))

    load = sum(w for _, _, w in hits)
    record = {
        "smoke_load": round(load, 1),
        "risk_level": risk_level(load, pm25_max_24h, thresholds),
        "fire_cells_total": len(cells),
        "fire_cells_upwind": len(hits),
        "pm25_now": pm25_now,
        "pm25_max_24h": pm25_max_24h,
        "ventilation": ventilation,
        "stagnation": stagnation_label(ventilation),
        "smoke_index": smoke_index(load, ventilation),
        "arrival_hour": None,
        "window_start_hour": None,
        "window_end_hour": None,
        "peak_hour": None,
        "contributors": [],
    }
    if hits:
        by_hour = sorted(((h, w) for h, _, w in hits), key=lambda p: p[0])
        record["arrival_hour"] = by_hour[0][0]
        record["window_start_hour"] = _quantile(by_hour, 0.10)
        record["window_end_hour"] = _quantile(by_hour, 0.90)
        record["peak_hour"] = _quantile(by_hour, 0.50)
        top = sorted(hits, key=lambda t: t[2], reverse=True)[:10]
        record["contributors"] = [
            {"lat": round(c.lat, 3), "lon": round(c.lon, 3), "frp": round(c.frp, 1),
             "fires": c.count, "arrival_hour": h, "weight": round(w, 1)}
            for h, c, w in top
        ]
    return record
