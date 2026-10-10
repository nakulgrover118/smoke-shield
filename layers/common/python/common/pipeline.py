"""Glue: raw inputs -> one risk record per city. Pure; the Lambda and the local runner both call this."""
from .cities import CITIES, STAGNATION_VALIDATED
from .filters import filter_fires
from .guidance import recommendation, school_plan
from .model import LEVELS, assess_city, cluster_fires, compute_paths


def build_records(fires, wind, aq, now, cities=None, fire_filter="all", met=None):
    cities = cities or CITIES
    raw_count = len(fires)
    fires, _ = filter_fires(fires, fire_filter)   # drop urban / repeat-burn detections before they become "smoke"
    cells = cluster_fires(fires)
    paths = compute_paths(cells, wind)   # city-independent: compute once, not per city
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    records = {}
    for key, city in cities.items():
        base = (aq or {}).get(key, {})
        rec = assess_city(city, cells, wind, base.get("pm25_now"), base.get("pm25_max_24h"), paths=paths,
                          ventilation=(met or {}).get(key))
        rec.update({"city": key, "name": city["name"], "name_hi": city.get("name_hi", city["name"]),
                    "lat": city["lat"], "lon": city["lon"], "stagnation_validated": key in STAGNATION_VALIDATED,
                    "generated_at": ts, "fires_total": raw_count, "fires_used": len(fires)})
        rec["recommendation"] = recommendation(rec)   # needs the fields above, so these are computed last
        rec["school"] = school_plan(rec)
        records[key] = rec
    return records


def level_rank(level):
    return LEVELS.index(level) if level in LEVELS else 0


def should_alert(previous, current, min_level="HIGH"):
    """Alert on escalation into/within HIGH+, not on every hourly refresh."""
    cur = level_rank(current["risk_level"])
    prev = level_rank(previous["risk_level"]) if previous else 0
    return cur >= level_rank(min_level) and cur > prev


def alert_text(rec):
    if rec.get("arrival_hour") is not None:
        when = (f"Smoke expected from ~{rec['arrival_hour']} h from now "
                f"(main window {rec['window_start_hour']}-{rec['window_end_hour']} h).")
    else:
        when = "Timing uncertain."
    return (f"SmokeShield: {rec['name']} smoke risk is {rec['risk_level']}. {when} "
            f"{rec['fire_cells_upwind']} active fire clusters are upwind.")
