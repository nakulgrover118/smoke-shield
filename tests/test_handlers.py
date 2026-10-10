import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import load_handler_module

RISK = {"pk": "RISK#delhi", "sk": "2026-10-08T06:00:00Z", "city": "delhi", "name": "Delhi", "risk_level": "HIGH",
        "arrival_hour": 12, "window_start_hour": 10, "window_end_hour": 18, "peak_hour": 14,
        "fire_cells_upwind": 7, "fire_cells_total": 14, "generated_at": "2026-10-08T06:00:00Z"}


def _event(path, city=None, qs=None):
    return {"rawPath": path, "pathParameters": {"city": city} if city else None, "queryStringParameters": qs}


def test_api_routes(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    api = load_handler_module("api")
    monkeypatch.setattr(api.store, "latest_risk", lambda t, c: RISK if c == "delhi" else None)

    cities = json.loads(api.handler(_event("/cities"), None)["body"])
    assert {c["key"] for c in cities} >= {"delhi", "jaipur"}

    assert json.loads(api.handler(_event("/risk/delhi", "delhi"), None)["body"])["risk_level"] == "HIGH"
    assert api.handler(_event("/risk/jaipur", "jaipur"), None)["statusCode"] == 404   # known city, no data
    assert api.handler(_event("/risk/atlantis", "atlantis"), None)["statusCode"] == 404
    assert len(json.loads(api.handler(_event("/risk"), None)["body"])) == 1


def test_advisory_generates_once_then_serves_cache(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("DISABLE_AGENT", "1")   # exercise the fallback path without Bedrock
    adv = load_handler_module("advisory")
    cache = {}
    monkeypatch.setattr(adv.store, "latest_risk", lambda t, c: RISK)
    monkeypatch.setattr(adv.store, "get_advisory", lambda t, c, ts, lang: cache.get((c, ts, lang)))
    monkeypatch.setattr(adv.store, "put_advisory", lambda t, c, ts, lang, a, now: cache.__setitem__((c, ts, lang), a))

    first = json.loads(adv.handler(_event("/advisory/delhi", "delhi", {"lang": "en"}), None)["body"])
    assert first["source"] == "fallback" and "Delhi" in first["advisory"]
    assert len(cache) == 1

    monkeypatch.setattr(adv, "generate_advisory", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")))
    second = json.loads(adv.handler(_event("/advisory/delhi", "delhi", {"lang": "en"}), None)["body"])
    assert second["advisory"] == first["advisory"]


def test_advisory_rejects_bad_input(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    adv = load_handler_module("advisory")
    assert adv.handler(_event("/advisory/atlantis", "atlantis"), None)["statusCode"] == 404
    assert adv.handler(_event("/advisory/delhi", "delhi", {"lang": "fr"}), None)["statusCode"] == 400


def test_ingest_stores_ventilation_and_snapshots_met(monkeypatch, sample_fires_csv):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.delenv("ALERT_TOPIC_ARN", raising=False)
    ing = load_handler_module("ingest")

    from common import sources
    from common.cities import CITIES
    now = sources.utcnow()
    times = [(now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
             for i in range(-1, 72)]
    met_payload = [{"hourly": {"time": times, "boundary_layer_height": [600.0] * len(times), "wind_speed_10m": [2.5] * len(times)}}
                   for _ in CITIES]
    monkeypatch.setattr(ing.sources, "fetch_fires_csv", lambda key: sample_fires_csv)
    monkeypatch.setattr(ing.sources, "fetch_wind_json", lambda: "wind")
    monkeypatch.setattr(ing.sources, "fetch_aq_json", lambda cities: None)
    monkeypatch.setattr(ing.sources, "fetch_met_json", lambda cities: met_payload)
    monkeypatch.setattr(ing.sources, "parse_wind", lambda payload, now: sources.synthetic_wind())

    saved, raws = {}, []
    monkeypatch.setattr(ing.store, "latest_risk", lambda t, c: None)
    monkeypatch.setattr(ing.store, "put_risk", lambda t, c, ts, rec, n: saved.__setitem__(c, rec))
    monkeypatch.setattr(ing.store, "put_raw", lambda b, k, body: raws.append(k))

    ing.handler({}, None)
    assert any(k.endswith("met.json") for k in raws)
    delhi = saved["delhi"]
    assert delhi["ventilation"]["vi_mean"] == 1500.0                       # 600 m x 2.5 m/s
    assert delhi["smoke_index"] == pytest.approx(delhi["smoke_load"] / 1500.0 * 1000.0, abs=0.1)   # load is stored rounded to 0.1


def test_ingest_end_to_end_with_fakes(monkeypatch, sample_fires_csv):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("ALERT_TOPIC_ARN", "arn:aws:sns:x:1:topic")
    ing = load_handler_module("ingest")

    from common import sources
    monkeypatch.setattr(ing.sources, "utcnow", lambda: datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc))   # the sample fires are from 08:12 that day
    monkeypatch.setattr(ing.sources, "fetch_fires_csv", lambda key: sample_fires_csv)
    monkeypatch.setattr(ing.sources, "fetch_wind_json", lambda: "wind")
    monkeypatch.setattr(ing.sources, "fetch_aq_json", lambda cities: (_ for _ in ()).throw(OSError("aq down")))
    monkeypatch.setattr(ing.sources, "fetch_met_json", lambda cities: (_ for _ in ()).throw(OSError("met down")))
    monkeypatch.setattr(ing.sources, "parse_wind", lambda payload, now: sources.synthetic_wind())

    puts, raws, alerts = [], [], []
    monkeypatch.setattr(ing.store, "latest_risk", lambda t, c: None)
    monkeypatch.setattr(ing.store, "put_risk", lambda t, c, ts, rec, now: puts.append(c))
    monkeypatch.setattr(ing.store, "put_raw", lambda b, k, body: raws.append(k))
    monkeypatch.setattr(ing.store, "publish_alert", lambda arn, subj, msg: alerts.append(subj))

    out = ing.handler({}, None)
    assert out["cities"] == 5 and out["fires"] == 17
    assert len(puts) == 5
    assert any(k.endswith("fires.csv") for k in raws) and not any(k.endswith("aq.json") for k in raws)   # AQ failure tolerated
    assert not any(k.endswith("met.json") for k in raws)                                                  # so is meteorology
    assert out["alerts"] == len(alerts)


def _ingest_with_fires(monkeypatch, fires_csv, now):
    """Run the ingest handler with a fake FIRMS response at a chosen clock time; returns (handler result, saved records)."""
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.delenv("RAW_BUCKET", raising=False)
    monkeypatch.delenv("ALERT_TOPIC_ARN", raising=False)
    ing = load_handler_module("ingest")
    from common import sources
    saved = {}
    monkeypatch.setattr(ing.sources, "utcnow", lambda: now)
    monkeypatch.setattr(ing.sources, "fetch_fires_csv", lambda key: fires_csv)
    monkeypatch.setattr(ing.sources, "fetch_wind_json", lambda: "wind")
    monkeypatch.setattr(ing.sources, "fetch_aq_json", lambda cities: None)
    monkeypatch.setattr(ing.sources, "fetch_met_json", lambda cities: (_ for _ in ()).throw(OSError("met down")))
    monkeypatch.setattr(ing.sources, "parse_wind", lambda payload, n: sources.synthetic_wind())
    monkeypatch.setattr(ing.store, "latest_risk", lambda t, c: None)
    monkeypatch.setattr(ing.store, "put_risk", lambda t, c, ts, rec, n: saved.__setitem__(c, rec))
    return ing.handler({}, None), saved


def test_ingest_just_after_midnight_utc_still_sees_yesterdays_fires(monkeypatch, sample_fires_csv):
    """Regression: with day_range=1 every run between 00:00 and ~10:00 UTC (the whole Indian school morning) saw zero fires."""
    out, saved = _ingest_with_fires(monkeypatch, sample_fires_csv, datetime(2026, 10, 9, 0, 19, tzinfo=timezone.utc))   # fires are 16 h old
    assert out["fires"] == 17 and saved["delhi"]["fires_used"] > 0


def test_ingest_ignores_fires_older_than_24_hours_and_warns(monkeypatch, sample_fires_csv, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        out, saved = _ingest_with_fires(monkeypatch, sample_fires_csv, datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc))   # 49 h later
    assert out["fires"] == 0 and saved["delhi"]["risk_level"] == "LOW"
    assert any("no detections in the last 24 h" in r.getMessage() for r in caplog.records)
