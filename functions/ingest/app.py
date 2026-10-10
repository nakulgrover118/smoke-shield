"""Hourly: fetch fires + wind + PM2.5 baseline, snapshot raw inputs to S3, write risk records, alert on escalation."""
import json
import logging
import os

from common import observability, pipeline, sources, store
from common.cities import CITIES

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event, context):
    now = sources.utcnow()
    table = os.environ["TABLE_NAME"]
    bucket = os.environ.get("RAW_BUCKET")
    topic = os.environ.get("ALERT_TOPIC_ARN")

    fires_csv = sources.fetch_fires_csv(os.environ.get("FIRMS_MAP_KEY"))
    wind_json = sources.fetch_wind_json()
    try:
        aq_json = sources.fetch_aq_json(CITIES)
    except Exception:  # the baseline is optional; the smoke forecast must still go out
        log.exception("air-quality baseline unavailable, continuing without it")
        aq_json = None

    try:
        met_json = sources.fetch_met_json(CITIES)
    except Exception:  # ventilation is context only; the forecast must still go out without it
        log.exception("meteorology (ventilation) unavailable, continuing without it")
        met_json = None

    fires = sources.parse_fires(fires_csv, now)          # exactly the last 24 h, by acquisition time
    if not fires:
        log.warning("FIRMS returned no detections in the last %d h; the smoke estimate will read LOW", sources.FIRE_WINDOW_HOURS)
    wind = sources.parse_wind(wind_json, now)
    aq = sources.parse_aq(aq_json, CITIES, now) if aq_json else {}
    met = sources.parse_ventilation(met_json, CITIES, now) if met_json else {}
    records = pipeline.build_records(fires, wind, aq, now, fire_filter=os.environ.get("FIRE_FILTER", "all"), met=met)

    if bucket:
        prefix = f"raw/{now:%Y/%m/%d/%H%M}"
        store.put_raw(bucket, f"{prefix}/fires.csv", fires_csv)
        store.put_raw(bucket, f"{prefix}/wind.json", json.dumps(wind_json))
        if aq_json:
            store.put_raw(bucket, f"{prefix}/aq.json", json.dumps(aq_json))
        if met_json:
            store.put_raw(bucket, f"{prefix}/met.json", json.dumps(met_json))   # lets backtest.py score ventilation on real forecasts

    alerts = 0
    for key, rec in records.items():
        previous = store.latest_risk(table, key)
        store.put_risk(table, key, rec["generated_at"], rec, now.timestamp())
        if topic and pipeline.should_alert(previous, rec):
            store.publish_alert(topic, f"Smoke alert: {rec['name']} {rec['risk_level']}", pipeline.alert_text(rec))
            alerts += 1

    # Raw JSON on stdout (not via `log`, whose prefix would break it): CloudWatch turns this line into custom metrics.
    print(observability.emf_line(observability.run_metrics(len(fires), records, alerts), now.timestamp() * 1000))
    log.info("ingest done: %d fires, %d cities, %d alerts", len(fires), len(records), alerts)
    return {"fires": len(fires), "cities": len(records), "alerts": alerts}
