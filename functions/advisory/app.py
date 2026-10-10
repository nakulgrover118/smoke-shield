"""GET /advisory/{city}?lang=en|hi - cached per risk record so the agent runs once per city per ingest."""
import json
import os
import time

from advisory_agent import LANGS, generate_advisory
from common import store
from common.cities import CITIES


def _resp(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    table = os.environ["TABLE_NAME"]
    city = (event.get("pathParameters") or {}).get("city")
    lang = (event.get("queryStringParameters") or {}).get("lang", "en")
    if city not in CITIES:
        return _resp(404, {"error": f"unknown city '{city}'", "known": list(CITIES)})
    if lang not in LANGS:
        return _resp(400, {"error": f"lang must be one of {list(LANGS)}"})

    risk = store.latest_risk(table, city)
    if not risk:
        return _resp(404, {"error": "no data yet - has the ingest run?"})

    cached = store.get_advisory(table, city, risk["sk"], lang)
    if cached:
        return _resp(200, {k: cached[k] for k in ("city", "lang", "risk_level", "advisory", "source", "risk_generated_at")})

    name = CITIES[city]["name_hi"] if lang == "hi" else CITIES[city]["name"]   # Hindi readers see the Hindi city name
    text, source = generate_advisory(name, risk, lang)
    out = {"city": city, "lang": lang, "risk_level": risk["risk_level"], "advisory": text,
           "source": source, "risk_generated_at": risk["generated_at"]}
    store.put_advisory(table, city, risk["sk"], lang, out, time.time())
    return _resp(200, out)
