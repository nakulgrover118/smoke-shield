"""Read API (HTTP API, payload v2): GET /cities, GET /risk, GET /risk/{city}."""
import json
import os

from common import store
from common.cities import CITIES


def _resp(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    path = event.get("rawPath", "")
    table = os.environ["TABLE_NAME"]

    if path.endswith("/cities"):
        return _resp(200, [{"key": k, **v} for k, v in CITIES.items()])

    city = (event.get("pathParameters") or {}).get("city")
    if city:
        if city not in CITIES:
            return _resp(404, {"error": f"unknown city '{city}'", "known": list(CITIES)})
        rec = store.latest_risk(table, city)
        return _resp(200, rec) if rec else _resp(404, {"error": "no data yet - has the ingest run?"})

    records = [r for r in (store.latest_risk(table, k) for k in CITIES) if r]
    return _resp(200, records)
