import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from common import observability, pipeline, sources
from common.cities import CITIES
from conftest import ROOT, load_handler_module


# ---- EMF line --------------------------------------------------------------------------------------------------

def test_emf_line_is_valid_embedded_metric_format():
    line = json.loads(observability.emf_line({"FiresRaw": 46, "FiresUsed": 40}, 1_760_000_000_000.0))
    meta = line["_aws"]
    assert meta["Timestamp"] == 1_760_000_000_000
    (block,) = meta["CloudWatchMetrics"]
    assert block["Namespace"] == "SmokeShield" and block["Dimensions"] == [[]]
    assert [m["Name"] for m in block["Metrics"]] == ["FiresRaw", "FiresUsed"]
    assert all(m["Unit"] == "Count" for m in block["Metrics"])
    assert line["FiresRaw"] == 46 and line["FiresUsed"] == 40            # values sit at the top level, as EMF requires


def test_every_declared_metric_has_a_value():
    metrics = {"A": 1, "B": 0}
    line = json.loads(observability.emf_line(metrics, 1))
    assert all(m["Name"] in line for m in line["_aws"]["CloudWatchMetrics"][0]["Metrics"])


# ---- run metrics -----------------------------------------------------------------------------------------------

def _records(met):
    now = datetime(2025, 11, 3, tzinfo=timezone.utc)
    return pipeline.build_records([], sources.synthetic_wind(), {}, now, met=met)


def test_run_metrics_count_cities_by_signal():
    poor = model_vent(120)       # POOR
    good = model_vent(900)       # GOOD
    met = {"delhi": poor, "gurugram": poor, "chandigarh": good, "ludhiana": good}          # jaipur: weather feed missing
    m = observability.run_metrics(46, _records(met), alerts=2)
    assert m == {"FiresRaw": 46, "FiresUsed": 0, "CitiesScored": 5, "CitiesPoorMixing": 2, "CitiesHighSmoke": 0,
                 "CitiesMissingWeather": 1, "AlertsSent": 2}


def test_run_metrics_with_no_records_does_not_crash():
    assert observability.run_metrics(0, {}, 0)["CitiesScored"] == 0


def model_vent(vi):
    from common import model
    return model.ventilation_stats([vi] * 48, [1.0] * 48)


# ---- the ingest emits it ---------------------------------------------------------------------------------------

def test_ingest_prints_one_parseable_emf_line(monkeypatch, capsys, sample_fires_csv):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.delenv("RAW_BUCKET", raising=False)
    monkeypatch.delenv("ALERT_TOPIC_ARN", raising=False)
    ing = load_handler_module("ingest")
    monkeypatch.setattr(ing.sources, "utcnow", lambda: datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc))   # inside the 24 h window of the sample fires
    monkeypatch.setattr(ing.sources, "fetch_fires_csv", lambda key: sample_fires_csv)
    monkeypatch.setattr(ing.sources, "fetch_wind_json", lambda: "wind")
    monkeypatch.setattr(ing.sources, "fetch_aq_json", lambda cities: None)
    monkeypatch.setattr(ing.sources, "fetch_met_json", lambda cities: (_ for _ in ()).throw(OSError("weather down")))
    monkeypatch.setattr(ing.sources, "parse_wind", lambda payload, now: sources.synthetic_wind())
    monkeypatch.setattr(ing.store, "latest_risk", lambda t, c: None)
    monkeypatch.setattr(ing.store, "put_risk", lambda *a: None)
    ing.handler({}, None)
    emf = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{") and "_aws" in l]
    assert len(emf) == 1
    assert emf[0]["FiresRaw"] == 17 and emf[0]["CitiesScored"] == len(CITIES)
    assert emf[0]["CitiesMissingWeather"] == len(CITIES)                  # weather feed was down: the dashboard would show it


# ---- the template ----------------------------------------------------------------------------------------------

def test_template_passes_cfn_lint():
    pytest.importorskip("cfnlint")
    from cfnlint.api import lint_all
    matches = lint_all((ROOT / "template.yaml").read_text(encoding="utf-8"))
    # E = errors, W = warnings. The I-level notes (explicit DeletionPolicy, architecture metadata) are deliberately not applied:
    # for a hackathon stack we want `sam delete` to remove everything.
    problems = [m for m in matches if m.rule.id[0] in "EW"]
    assert not problems, [f"{m.rule.id} line {m.linenumber}: {m.message}" for m in problems]


def test_dashboard_body_is_valid_json_after_substitution():
    import re
    import textwrap
    text = (ROOT / "template.yaml").read_text(encoding="utf-8")
    block = text.split("OpsDashboard:")[1].split("Fn::Sub:")[1].split("\n          - |\n")[1].split("\n          - Region:")[0]
    body = re.sub(r"\$\{[A-Za-z]+\}", "x", textwrap.dedent(block))       # every ${Placeholder} becomes a dummy value
    widgets = json.loads(body)["widgets"]
    assert [w["type"] for w in widgets].count("alarm") == 1 and len(widgets) == 10
    for w in widgets:
        assert w["width"] + w["x"] <= 24                                  # stays inside the 24-column grid
        if w["type"] == "metric":
            assert w["properties"]["metrics"] and w["properties"]["title"]
    custom = {m[1] for w in widgets if w["type"] == "metric" for m in w["properties"]["metrics"] if m[0] == "SmokeShield"}
    emitted = set(observability.run_metrics(0, {}, 0))
    assert custom <= emitted, custom - emitted                            # the dashboard only plots metrics the ingest really emits
    alarm_arns = next(w for w in widgets if w["type"] == "alarm")["properties"]["alarms"]
    assert len(alarm_arns) == 5


def test_no_fires_alarm_watches_the_metric_the_ingest_emits_and_needs_three_in_a_row():
    text = (ROOT / "template.yaml").read_text(encoding="utf-8")
    block = text.split("IngestNoFiresAlarm:")[1].split("ApiServerErrorsAlarm:")[0]
    assert "MetricName: FiresRaw" in block and "FiresRaw" in observability.run_metrics(0, {}, 0)
    assert "EvaluationPeriods: 3" in block and "DatapointsToAlarm: 3" in block and "LessThanThreshold" in block
    assert "TreatMissingData: notBreaching" in block                  # silence is the staleness alarm's job; this one is about 'ran, saw nothing'


def test_template_has_the_operational_pieces_and_they_are_wired_together():
    text = (ROOT / "template.yaml").read_text(encoding="utf-8")
    for needle in ("OpsTopic:", "IngestDLQ:", "IngestErrorsAlarm:", "IngestStaleAlarm:", "IngestNoFiresAlarm:", "ApiServerErrorsAlarm:",
                   "IngestDLQAlarm:", "OpsDashboard:", "DeadLetterQueue:", "EventInvokeConfig:", "RetentionInDays: 30"):
        assert needle in text, needle
    assert text.count("AlarmActions: [!Ref OpsTopic]") == 5           # every alarm tells someone
    assert text.count("LoggingConfig:") == 3                            # all three functions use a log group with retention
    stale = text.split("IngestStaleAlarm:")[1].split("ApiServerErrorsAlarm:")[0]
    assert "TreatMissingData: breaching" in stale                       # silence must count as failure for the staleness alarm
