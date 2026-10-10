from datetime import datetime, timezone

import pytest
from common import pipeline, sources, store
from common.cities import CITIES, grid_points
from common.guidance import fallback_advisory


def test_parse_fires_drops_low_confidence_and_garbage(sample_fires_csv):
    fires = sources.parse_fires(sample_fires_csv)
    assert len(fires) == 17   # 18 rows, 1 low-confidence
    assert sources.parse_fires("Invalid MAP_KEY") == []


def _fire_csv(*rows):
    """rows: (acq_date, acq_time) pairs -> a FIRMS-style CSV with one detection per row."""
    head = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
    return head + "".join(f"30.{i},76.{i},340,0.4,0.4,{d},{t},N,VIIRS,n,2.0NRT,300,{10 + i}.0,D\n" for i, (d, t) in enumerate(rows))


NOW = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def test_parse_fires_keeps_exactly_the_last_24_hours():
    csv_text = _fire_csv(("2026-10-10", "0530"),      # 30 min ago
                         ("2026-10-09", "0600"),      # exactly 24 h ago: kept (boundary is inclusive)
                         ("2026-10-09", "0559"),      # 24 h 1 min ago: dropped
                         ("2026-10-08", "2300"),      # 31 h ago: dropped
                         ("2026-10-09", "2319"))      # last night's pass
    kept = sources.parse_fires(csv_text, NOW)
    assert [round(f["frp"]) for f in kept] == [10, 11, 14]            # rows 0, 1 and 4
    assert len(sources.parse_fires(csv_text)) == 5                    # without `now` nothing is filtered (back-test behaviour)


def test_parse_fires_window_is_the_fix_for_the_empty_morning():
    """Just after midnight UTC, 'today so far' is empty but yesterday's passes are still within 24 h."""
    just_after_midnight = datetime(2026, 10, 10, 0, 19, tzinfo=timezone.utc)
    csv_text = _fire_csv(("2026-10-09", "0812"), ("2026-10-09", "2002"), ("2026-10-09", "2319"))   # nothing dated Oct 10 yet
    assert len(sources.parse_fires(csv_text, just_after_midnight)) == 3
    midmorning = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    assert len(sources.parse_fires(csv_text, midmorning)) == 2                                      # the 08:12 detection has aged out


def test_parse_fires_tolerates_unpadded_times_future_rows_and_missing_times():
    csv_text = _fire_csv(("2026-10-10", "812"),       # FIRMS-style 0812 written as 812 -> 08:12, which is in the future at 06:00
                         ("2026-10-10", "0610"),      # 10 min ahead of `now`: inside the clock-skew allowance, kept
                         ("2026-10-10", "0700"))      # an hour ahead: dropped
    assert [round(f["frp"]) for f in sources.parse_fires(csv_text, NOW)] == [11]
    no_times = "latitude,longitude,frp,confidence\n30.1,76.1,12.0,n\n"
    assert len(sources.parse_fires(no_times, NOW)) == 1                # cannot judge the age, so keep it
    broken = _fire_csv(("not-a-date", "xx"))
    assert len(sources.parse_fires(broken, NOW)) == 1


def test_fetch_fires_asks_for_two_days_not_one(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_get", lambda url: seen.append(url) or "latitude,longitude\n")
    sources.fetch_fires_csv("KEY")
    assert seen[0].endswith("/2")                                      # day_range=1 means 'today since 00:00 UTC': empty until ~10:00 UTC
    sources.fetch_fires_csv("KEY", day_range=3)
    assert seen[1].endswith("/3")
    with pytest.raises(RuntimeError):
        sources.fetch_fires_csv("")


def _open_meteo_payload(points, times, speed, direction):
    return [{"hourly": {"time": times, "wind_speed_10m": [speed] * len(times),
                        "wind_direction_10m": [direction] * len(times)}} for _ in points]


def test_parse_wind_starts_at_current_hour():
    pts = grid_points()
    times = [f"2026-10-08T{h:02d}:00" for h in range(24)]
    payload = _open_meteo_payload(pts, times, 12.0, 300.0)
    payload[0]["hourly"]["wind_speed_10m"][5] = 99.0   # marker at 05:00
    now = datetime(2026, 10, 8, 5, 40, tzinfo=timezone.utc)
    wf = sources.parse_wind(payload, now)
    assert wf.points[pts[0]][0] == (99.0, 300.0)       # index 0 == 05:00
    assert len(wf.points[pts[0]]) == 19


def test_parse_aq_handles_single_and_nulls():
    cities = {"delhi": CITIES["delhi"]}
    times = [f"2026-10-08T{h:02d}:00" for h in range(24)]
    payload = {"hourly": {"time": times, "pm2_5": [None] * 10 + [80.0, 120.0] + [90.0] * 12}}
    now = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
    out = sources.parse_aq(payload, cities, now)
    assert out["delhi"] == {"pm25_now": 80.0, "pm25_max_24h": 120.0}


def test_build_records_covers_all_cities(sample_fires_csv):
    now = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
    recs = pipeline.build_records(sources.parse_fires(sample_fires_csv), sources.synthetic_wind(), {}, now)
    assert set(recs) == set(CITIES)
    assert recs["delhi"]["generated_at"] == "2026-10-08T06:00:00Z"
    assert recs["delhi"]["name"] == "Delhi"


def test_should_alert_only_on_escalation_to_high():
    hi, sev, mod = ({"risk_level": x} for x in ("HIGH", "SEVERE", "MODERATE"))
    assert pipeline.should_alert(None, hi)
    assert not pipeline.should_alert(hi, hi)            # no repeat alerts every hour
    assert pipeline.should_alert(hi, sev)
    assert not pipeline.should_alert(sev, hi)           # de-escalation is silent
    assert not pipeline.should_alert(None, mod)


def test_fallback_advisory_mentions_timing_and_disclaimer(sample_fires_csv):
    now = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
    rec = pipeline.build_records(sources.parse_fires(sample_fires_csv), sources.synthetic_wind(), {}, now)["delhi"]
    text = fallback_advisory("Delhi", rec)
    assert "Delhi" in text and rec["risk_level"] in text
    assert "not medical advice" in text
    assert f"{rec['arrival_hour']} h" in text


def test_ddb_roundtrip_has_no_floats():
    item = store.to_ddb({"a": 1.5, "b": [{"c": 2.25}], "d": 3})
    assert not isinstance(item["a"], float) and not isinstance(item["b"][0]["c"], float)
    assert store.from_ddb(item) == {"a": 1.5, "b": [{"c": 2.25}], "d": 3}
