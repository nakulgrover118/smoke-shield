import json
import re
from datetime import datetime, timezone

import pytest
from common import guidance, model, pipeline, sources
from common.cities import CITIES
from conftest import ROOT, load_handler_module

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LEVELS = ["LOW", "MODERATE", "HIGH", "SEVERE"]


def risk(level="LOW", stagnation=None, validated=True, **extra):
    base = {"risk_level": level, "arrival_hour": None, "window_start_hour": None, "window_end_hour": None,
            "fire_cells_upwind": 0, "fire_cells_total": 0, "stagnation": stagnation, "stagnation_validated": validated}
    return {**base, **extra}


# ---- the two languages stay in step -------------------------------------------------------------------------------

@pytest.mark.parametrize("level", LEVELS)
def test_hindi_guidance_mirrors_english_structure(level):
    en, hi = guidance.GUIDANCE[level], guidance.GUIDANCE_HI[level]
    assert set(en) == set(hi) == {"headline", "short", "actions"}
    assert len(en["actions"]) == len(hi["actions"])          # a translation must not drop or invent an action
    for text in [hi["headline"], hi["short"], *hi["actions"]]:
        assert DEVANAGARI.search(text), text


def test_hindi_stagnation_guidance_mirrors_english():
    assert set(guidance.STAGNATION_GUIDANCE) == set(guidance.STAGNATION_GUIDANCE_HI)
    for label, en in guidance.STAGNATION_GUIDANCE.items():
        hi = guidance.STAGNATION_GUIDANCE_HI[label]
        assert set(en) == set(hi) and len(en["actions"]) == len(hi["actions"])
        assert all(DEVANAGARI.search(s) for s in [hi["headline"], hi["short"], hi["note"], *hi["actions"]])


def test_every_level_has_a_hindi_name_and_every_city_a_hindi_name():
    assert set(guidance.LEVEL_NAMES_HI) == set(LEVELS)
    for key, c in CITIES.items():
        assert DEVANAGARI.search(c["name_hi"]), key


def test_guidance_lookup_by_language_and_unknown_inputs():
    assert guidance.guidance_for("HIGH", "hi") is guidance.GUIDANCE_HI["HIGH"]
    assert guidance.guidance_for("HIGH") is guidance.GUIDANCE["HIGH"]
    assert guidance.guidance_for("bogus", "hi") is guidance.GUIDANCE_HI["LOW"]
    assert guidance.stagnation_guidance("POOR", "hi")["headline"] == guidance.STAGNATION_GUIDANCE_HI["POOR"]["headline"]
    assert guidance.stagnation_guidance("GOOD", "hi") is None


# ---- Hindi template advisory --------------------------------------------------------------------------------------

def test_hindi_advisory_is_hindi_complete_and_has_the_disclaimer():
    r = risk("MODERATE", "POOR", arrival_hour=6, window_start_hour=6, window_end_hour=23, fire_cells_upwind=9, fire_cells_total=12)
    text = guidance.fallback_advisory("दिल्ली", r, "hi")
    assert text.startswith("दिल्ली:") and "मध्यम" in text
    assert "लगभग 6 घंटे में" in text and "6 से 23 घंटे के बीच" in text and "12 में से 9" in text
    assert "हवा का मिश्रण:" in text                              # poor-mixing note for a validated city
    assert text.rstrip().endswith("चिकित्सकीय सलाह नहीं।")
    for english in ("Suggested actions", "not medical advice", "upwind", "Air mixing"):
        assert english not in text                                # nothing left untranslated


def test_hindi_advisory_single_hour_window_and_low_wording():
    r = risk("LOW", arrival_hour=4, window_start_hour=4, window_end_hour=4, fire_cells_upwind=1, fire_cells_total=19)
    text = guidance.fallback_advisory("गुरुग्राम", r, "hi")
    assert "थोड़ा-सा धुआँ" in text and "लगभग 4 घंटे के आसपास" in text and "4 से 4" not in text


@pytest.mark.parametrize("label, validated", [("POOR", False), ("MODERATE", True), ("GOOD", True), (None, True)])
def test_hindi_advisory_air_mixing_note_follows_the_same_rules_as_english(label, validated):
    assert "हवा का मिश्रण:" not in guidance.fallback_advisory("दिल्ली", risk("LOW", label, validated), "hi")


def test_english_advisory_unchanged_by_the_language_argument():
    r = risk("HIGH", "POOR", arrival_hour=5, window_start_hour=5, window_end_hour=9, fire_cells_upwind=3, fire_cells_total=10)
    assert guidance.fallback_advisory("Delhi", r) == guidance.fallback_advisory("Delhi", r, "en")
    assert not DEVANAGARI.search(guidance.fallback_advisory("Delhi", r))


# ---- the one-line recommendation ---------------------------------------------------------------------------------

@pytest.mark.parametrize("level, tone", [("LOW", "ok"), ("MODERATE", "caution"), ("HIGH", "alert"), ("SEVERE", "alert")])
def test_recommendation_tone_follows_smoke_level(level, tone):
    rec = guidance.recommendation(risk(level))
    assert rec["tone"] == tone
    assert rec["en"] == guidance.GUIDANCE[level]["short"] and rec["hi"] == guidance.GUIDANCE_HI[level]["short"]


def test_poor_air_mixing_adds_a_sentence_and_raises_an_ok_day_to_caution():
    rec = guidance.recommendation(risk("LOW", "POOR", True))
    assert rec["tone"] == "caution"
    assert rec["en"].startswith("No smoke precautions needed.") and "prefer midday or afternoon" in rec["en"]
    assert DEVANAGARI.search(rec["hi"]) and "दोपहर" in rec["hi"]
    assert guidance.recommendation(risk("HIGH", "POOR", True))["tone"] == "alert"      # never lowered


@pytest.mark.parametrize("label, validated", [("POOR", False), ("GOOD", True), ("MODERATE", True), (None, True)])
def test_recommendation_ignores_air_mixing_unless_poor_and_validated(label, validated):
    rec = guidance.recommendation(risk("LOW", label, validated))
    assert rec == guidance.recommendation(risk("LOW")) and rec["tone"] == "ok"


def test_pipeline_attaches_recommendation_and_hindi_names_to_every_record():
    now = datetime(2025, 11, 3, tzinfo=timezone.utc)
    met = {k: model.ventilation_stats([120.0] * 48, [1.0] * 48) for k in CITIES}
    recs = pipeline.build_records([], sources.synthetic_wind(), {}, now, met=met)
    for key, rec in recs.items():
        assert rec["name_hi"] == CITIES[key]["name_hi"]
        assert set(rec["recommendation"]) == {"en", "hi", "tone"}
    assert recs["delhi"]["recommendation"]["tone"] == "caution" and "midday" in recs["delhi"]["recommendation"]["en"]
    assert recs["jaipur"]["recommendation"]["tone"] == "ok"             # not validated: stays quiet
    json.dumps(recs)                                                    # the whole record must stay JSON-safe


# ---- the endpoint ------------------------------------------------------------------------------------------------

def test_advisory_endpoint_serves_hindi_template_with_hindi_city_name(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("DISABLE_AGENT", "1")
    adv = load_handler_module("advisory")
    rec = {**risk("MODERATE", "POOR", arrival_hour=6, window_start_hour=6, window_end_hour=20, fire_cells_upwind=2, fire_cells_total=5),
           "sk": "2026-10-08T06:00:00Z", "city": "delhi", "name": "Delhi", "generated_at": "2026-10-08T06:00:00Z"}
    cache = {}
    monkeypatch.setattr(adv.store, "latest_risk", lambda t, c: rec)
    monkeypatch.setattr(adv.store, "get_advisory", lambda t, c, ts, lang: cache.get((c, ts, lang)))
    monkeypatch.setattr(adv.store, "put_advisory", lambda t, c, ts, lang, a, now: cache.__setitem__((c, ts, lang), a))

    def call(lang):
        return json.loads(adv.handler({"pathParameters": {"city": "delhi"}, "queryStringParameters": {"lang": lang}}, None)["body"])
    hi, en = call("hi"), call("en")
    assert hi["source"] == "fallback" and hi["lang"] == "hi" and hi["advisory"].startswith("दिल्ली:")
    assert en["advisory"].startswith("Delhi:") and not DEVANAGARI.search(en["advisory"])
    assert set(k[2] for k in cache) == {"hi", "en"}                     # cached separately per language


# ---- the shipped offline demo data -------------------------------------------------------------------------------

def test_shipped_mock_data_matches_the_frontend_contract():
    mock = json.loads((ROOT / "frontend" / "mock.json").read_text(encoding="utf-8"))
    assert {r["city"] for r in mock["risk"]} == set(CITIES)
    for r in mock["risk"]:
        assert r["recommendation"]["hi"] and r["name_hi"] == CITIES[r["city"]]["name_hi"]
        for lang in ("en", "hi"):
            a = mock["advisory"][r["city"]][lang]
            assert a["lang"] == lang and a["advisory"]
        assert DEVANAGARI.search(mock["advisory"][r["city"]]["hi"]["advisory"])
    delhi = next(r for r in mock["risk"] if r["city"] == "delhi")
    assert delhi["stagnation"] == "POOR" and delhi["recommendation"]["tone"] == "caution"      # the scripted demo scenario
