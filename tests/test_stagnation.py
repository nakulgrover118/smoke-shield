import json
from datetime import datetime, timezone

import pytest
from common import guidance, model, pipeline, sources
from common.cities import CITIES, STAGNATION_VALIDATED
from conftest import load_handler_module


def vent(vi):
    """Constant ventilation of `vi` m2/s over 48 h."""
    return model.ventilation_stats([vi] * 48, [1.0] * 48)


# ---- the label -----------------------------------------------------------------------------

@pytest.mark.parametrize("vi, expected", [(120, "POOR"), (164, "POOR"), (165, "MODERATE"), (200, "MODERATE"),
                                          (239, "MODERATE"), (240, "GOOD"), (900, "GOOD")])
def test_stagnation_label_boundaries(vi, expected):
    assert model.stagnation_label(vent(vi)) == expected


def test_stagnation_label_without_meteorology_is_none():
    assert model.stagnation_label(None) is None
    assert model.stagnation_label({}) is None


def test_label_uses_effective_ventilation_so_one_stagnant_night_counts():
    # Mean VI is 1100 (looks well ventilated) but half the hours are near-calm nights at the 100 m2/s floor.
    mixed = model.ventilation_stats([2000.0] * 24 + [100.0] * 24, [1.0] * 48)
    assert mixed["vi_mean"] > 1000 and mixed["vi_eff"] < 200
    assert model.stagnation_label(mixed) == "MODERATE"          # not GOOD, despite the high mean
    assert model.stagnation_label(model.ventilation_stats([2000.0] * 48, [1.0] * 48)) == "GOOD"


def test_vi_eff_is_reported_and_consistent():
    v = vent(150)
    assert v["vi_eff"] == pytest.approx(150.0, abs=0.1) and v["inv_vi"] == pytest.approx(1 / 150)


def test_cutoffs_stay_inside_the_range_the_data_covers():
    # The data behind the cut-offs spanned roughly 135-640 m2/s; a cut-off outside that would be unsupported.
    assert 135 < model.STAGNATION_POOR_BELOW < model.STAGNATION_GOOD_FROM < 640


def test_label_does_not_change_risk_level():
    delhi = CITIES["delhi"]
    plain = model.assess_city(delhi, [], sources.synthetic_wind())
    poor = model.assess_city(delhi, [], sources.synthetic_wind(), ventilation=vent(120))
    assert plain["stagnation"] is None and poor["stagnation"] == "POOR"
    assert poor["risk_level"] == plain["risk_level"] == "LOW"


# ---- pipeline / validated cities -----------------------------------------------------------

def test_records_flag_validated_cities_only():
    now = datetime(2025, 11, 3, tzinfo=timezone.utc)
    met = {k: vent(120) for k in CITIES}
    recs = pipeline.build_records([], sources.synthetic_wind(), {}, now, met=met)
    assert {k for k, r in recs.items() if r["stagnation_validated"]} == STAGNATION_VALIDATED == {"delhi", "gurugram"}
    assert all(r["stagnation"] == "POOR" for r in recs.values())


# ---- advisory text -------------------------------------------------------------------------

def risk(label, validated, level="LOW"):
    return {"risk_level": level, "arrival_hour": None, "window_start_hour": None, "window_end_hour": None,
            "fire_cells_upwind": 0, "fire_cells_total": 0, "stagnation": label, "stagnation_validated": validated}


def test_stagnation_guidance_table():
    assert guidance.stagnation_guidance("POOR")["actions"]
    assert guidance.stagnation_guidance("GOOD") is None and guidance.stagnation_guidance("MODERATE") is None
    assert guidance.stagnation_guidance("bogus") is None


def test_poor_mixing_adds_a_note_even_when_smoke_risk_is_low():
    text = guidance.fallback_advisory("Delhi", risk("POOR", True))
    assert "Air mixing: air is expected to mix poorly" in text and "midday or afternoon" in text
    assert "not medical advice" in text


@pytest.mark.parametrize("label, validated", [("POOR", False), ("MODERATE", True), ("GOOD", True), (None, True)])
def test_no_air_mixing_text_unless_poor_and_validated(label, validated):
    assert "Air mixing" not in guidance.fallback_advisory("Delhi", risk(label, validated))


def test_advisory_wording_for_single_hour_window_and_single_cluster():
    base = {**risk("GOOD", True), "risk_level": "LOW", "arrival_hour": 5, "fire_cells_total": 19}
    one = guidance.fallback_advisory("Delhi", {**base, "window_start_hour": 5, "window_end_hour": 5, "fire_cells_upwind": 1})
    assert "mostly around 5 h from now" in one and "1 of 19 active fire clusters is upwind" in one
    assert "between 5 h and 5 h" not in one
    many = guidance.fallback_advisory("Delhi", {**base, "window_start_hour": 6, "window_end_hour": 23, "fire_cells_upwind": 9})
    assert "mostly between 6 h and 23 h from now" in many and "9 of 19 active fire clusters are upwind" in many


def test_advisory_endpoint_includes_the_note(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("DISABLE_AGENT", "1")
    adv = load_handler_module("advisory")
    rec = {**risk("POOR", True, "MODERATE"), "sk": "2026-10-08T06:00:00Z", "city": "delhi", "name": "Delhi",
           "generated_at": "2026-10-08T06:00:00Z", "arrival_hour": 6, "window_start_hour": 6, "window_end_hour": 20}
    monkeypatch.setattr(adv.store, "latest_risk", lambda t, c: rec)
    monkeypatch.setattr(adv.store, "get_advisory", lambda *a: None)
    monkeypatch.setattr(adv.store, "put_advisory", lambda *a: None)
    out = json.loads(adv.handler({"pathParameters": {"city": "delhi"}, "queryStringParameters": {"lang": "en"}}, None)["body"])
    assert "Air mixing" in out["advisory"]


# ---- the Strands agent (skipped where strands isn't installed) -------------------------------

def test_agent_registers_stagnation_tool_and_gates_advice_by_validation(monkeypatch):
    pytest.importorskip("strands")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    import advisory_agent as aa
    agent = aa._build_agent({**risk("POOR", True), "name": "Delhi"})
    assert set(agent.tool_names) == {"get_smoke_forecast", "get_school_guidance", "get_stagnation_guidance"}
    forecast = json.loads(agent.tool.get_smoke_forecast()["content"][0]["text"])
    assert forecast["stagnation_advice"] == "POOR"
    guide = json.loads(agent.tool.get_stagnation_guidance(label="poor")["content"][0]["text"])
    assert guide["actions"]
    jaipur = aa._build_agent({**risk("POOR", False), "name": "Jaipur"})
    assert json.loads(jaipur.tool.get_smoke_forecast()["content"][0]["text"])["stagnation_advice"] is None
