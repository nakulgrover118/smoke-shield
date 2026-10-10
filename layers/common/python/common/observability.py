"""Custom CloudWatch metrics via the Embedded Metric Format (EMF).

Printing one JSON line to stdout is enough: CloudWatch Logs extracts the numbers into metrics, so there is no SDK call,
no extra IAM permission and no latency. The ingest emits one line per run; the dashboard and alarms read them.
"""
import json

NAMESPACE = "SmokeShield"


def emf_line(metrics, now_ms, namespace=NAMESPACE, unit="Count"):
    """One JSON log line that CloudWatch turns into custom metrics. `metrics` is {name: number}."""
    return json.dumps({
        "_aws": {"Timestamp": int(now_ms),
                 "CloudWatchMetrics": [{"Namespace": namespace, "Dimensions": [[]],
                                        "Metrics": [{"Name": name, "Unit": unit} for name in metrics]}]},
        **metrics})


def run_metrics(fires_raw, records, alerts):
    """Numbers that say 'is the pipeline healthy and what did it see this hour?' for one ingest run."""
    recs = list(records.values())
    return {
        "FiresRaw": fires_raw,                                                       # detections fetched from FIRMS
        "FiresUsed": recs[0]["fires_used"] if recs else 0,                           # ...after the crop-fire filter
        "CitiesScored": len(recs),
        "CitiesPoorMixing": sum(r.get("stagnation") == "POOR" for r in recs),
        "CitiesHighSmoke": sum(r["risk_level"] in ("HIGH", "SEVERE") for r in recs),
        "CitiesMissingWeather": sum(r.get("ventilation") is None for r in recs),     # >0 means the weather feed was down
        "AlertsSent": alerts,
    }
