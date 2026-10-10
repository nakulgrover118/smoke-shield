import itertools
import json
import re
from datetime import datetime, timezone

import pytest
from common import guidance, model, pipeline, sources
from common.cities import CITIES
from conftest import ROOT

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SMOKE = ["LOW", "MODERATE", "HIGH", "SEVERE"]
RANK = {"ok": 0, "limit": 1, "avoid": 2}


def risk(level="LOW", stagnation=None, validated=True, **extra):
    base = {"risk_level": level, "arrival_hour": None, "window_start_hour": None, "window_end_hour": None,
            "fire_cells_upwind": 0, "fire_cells_total": 0, "stagnation": stagnation, "stagnation_validated": validated}
    return {**base, **extra}


def row(plan, activity):
    return next(a for a in plan["activities"] if a["id"] == activity)


# ---- the status matrix: every combination of smoke level and air mixing --------------------------------------------

@pytest.mark.parametrize("level, mixing, validated", list(itertools.product(SMOKE, ["POOR", "MODERATE", "GOOD", None], [True, False])))
def test_overall_status_is_the_worse_of_smoke_and_validated_poor_mixing(level, mixing, validated):
    plan = guidance.school_plan(risk(level, mixing, validated))
    smoke = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 2}[level]
    mix = 1 if (mixing == "POOR" and validated) else 0        # unvalidated or non-POOR mixing never restricts anything
    assert RANK[plan["status"]] == max(smoke, mix)


def test_poor_mixing_in_an_unvalidated_city_changes_nothing():
    assert guidance.school_plan(risk("LOW", "POOR", validated=False)) == guidance.school_plan(risk("LOW", None))


@pytest.mark.parametrize("level, mixing, expected", [
    ("LOW", "GOOD", "ok"), ("LOW", "MODERATE", "ok"), ("LOW", "POOR", "limit"),
    ("MODERATE", "GOOD", "limit"), ("HIGH", "GOOD", "avoid"), ("SEVERE", "POOR", "avoid")])
def test_headline_examples(level, mixing, expected):
    plan = guidance.school_plan(risk(level, mixing))
    assert plan["status"] == expected
    assert plan["headline"]["en"].endswith(guidance.STATUS_WORDS["en"][expected])
    assert plan["headline"]["hi"].endswith(guidance.STATUS_WORDS["hi"][expected])


def test_recommendation_tone_agrees_with_the_school_status():
    """The card colour and the planner status must never contradict each other."""
    tone_of = {"ok": "ok", "limit": "caution", "avoid": "alert"}
    for level, mixing in itertools.product(SMOKE, ["POOR", "GOOD", None]):
        r = risk(level, mixing)
        assert guidance.recommendation(r)["tone"] == tone_of[guidance.school_plan(r)["status"]], (level, mixing)


# ---- activities --------------------------------------------------------------------------------------------------

def test_all_six_activities_present_and_bilingual_for_every_status():
    for level, mixing in itertools.product(SMOKE, ["POOR", "GOOD"]):
        plan = guidance.school_plan(risk(level, mixing))
        assert [a["id"] for a in plan["activities"]] == ["assembly", "pe", "recess", "classroom", "vulnerable", "parents"]
        for a in plan["activities"]:
            assert a["status"] in RANK and a["text"]["en"] and DEVANAGARI.search(a["text"]["hi"]), a


def test_every_text_in_the_table_has_a_hindi_version_in_devanagari():
    for activity, by_status in guidance.ACTIVITY_TEXT.items():
        for status, (en, hi) in by_status.items():
            assert en and DEVANAGARI.search(hi), (activity, status)
    assert DEVANAGARI.search(guidance.BEST_TIME[1])
    assert set(guidance.STATUS_WORDS["en"]) == set(guidance.STATUS_WORDS["hi"]) == {"ok", "limit", "avoid"}


def test_recess_follows_smoke_only_and_classroom_only_reacts_to_heavy_smoke():
    assert row(guidance.school_plan(risk("LOW", "POOR")), "recess")["status"] == "ok"        # poor mixing alone: breaks stay normal
    assert row(guidance.school_plan(risk("MODERATE")), "recess")["status"] == "limit"
    assert row(guidance.school_plan(risk("MODERATE")), "classroom")["status"] == "ok"
    heavy = row(guidance.school_plan(risk("HIGH")), "classroom")
    assert heavy["status"] == "limit" and "windows" in heavy["text"]["en"]


def test_children_with_asthma_are_always_covered_and_escalate_with_the_status():
    assert row(guidance.school_plan(risk("LOW", "GOOD")), "vulnerable")["status"] == "ok"
    assert row(guidance.school_plan(risk("MODERATE")), "vulnerable")["status"] == "limit"
    severe = row(guidance.school_plan(risk("SEVERE")), "vulnerable")
    assert severe["status"] == "avoid" and "without penalty" in severe["text"]["en"]


# ---- timing ------------------------------------------------------------------------------------------------------

def test_best_time_only_when_poor_mixing_applies():
    assert guidance.school_plan(risk("LOW", "POOR"))["best_time"]["en"].endswith("midday to afternoon.")
    assert guidance.school_plan(risk("LOW", "GOOD"))["best_time"] is None
    assert guidance.school_plan(risk("LOW", "POOR", validated=False))["best_time"] is None


def test_smoke_window_text_for_range_single_hour_and_none():
    rng = guidance.school_plan(risk("MODERATE", arrival_hour=6, window_start_hour=6, window_end_hour=23))["smoke_window"]
    assert rng["en"] == "Smoke expected roughly 6-23 hours from now." and DEVANAGARI.search(rng["hi"]) and "6-23" in rng["hi"]
    one = guidance.school_plan(risk("HIGH", arrival_hour=4, window_start_hour=4, window_end_hour=4))["smoke_window"]
    assert "around 4 hours" in one["en"] and "4-4" not in one["hi"]
    assert guidance.school_plan(risk("LOW", arrival_hour=4, window_start_hour=4, window_end_hour=4))["smoke_window"] is None   # no window for LOW
    assert guidance.school_plan(risk("MODERATE"))["smoke_window"] is None                                                       # no arrival data


# ---- the parent notice --------------------------------------------------------------------------------------------

def test_notice_matches_the_status_in_both_languages():
    ok = guidance.school_plan(risk("LOW", "GOOD"))["notice"]
    assert "run as usual" in ok["en"] and DEVANAGARI.search(ok["hi"])
    smoke = guidance.school_plan(risk("MODERATE", "GOOD"))["notice"]
    assert "some crop-fire smoke" in smoke["en"] and "air mixing" not in smoke["en"] and "inhalers" in smoke["en"]
    both = guidance.school_plan(risk("MODERATE", "POOR"))["notice"]
    assert "shows that some crop-fire smoke may reach our city and that air mixing may be poor" in both["en"]   # reads as one sentence
    assert "midday to afternoon" in both["en"]
    poor_only = guidance.school_plan(risk("LOW", "POOR"))["notice"]
    assert "air mixing may be poor" in poor_only["en"] and "crop-fire smoke" not in poor_only["en"]
    heavy = guidance.school_plan(risk("HIGH", "GOOD"))["notice"]
    assert "cancel outdoor PE" in heavy["en"] and "without penalty" in heavy["en"]


def test_notice_never_leaves_template_placeholders_or_english_in_the_hindi_version():
    for level, mixing in itertools.product(SMOKE, ["POOR", "GOOD", None]):
        notice = guidance.school_plan(risk(level, mixing))["notice"]
        for lang, text in notice.items():
            assert "{" not in text and "}" not in text and text.strip(), (level, mixing, lang)
        assert DEVANAGARI.search(notice["hi"])
        assert not re.search(r"[A-Za-z]{4,}", notice["hi"]), notice["hi"]        # no untranslated English words


def test_notice_makes_no_medical_or_safety_claims():
    for level, mixing in itertools.product(SMOKE, ["POOR", "GOOD"]):
        text = guidance.school_plan(risk(level, mixing))["notice"]["en"].lower()
        assert "safe" not in text and "harmless" not in text and "cure" not in text


# ---- wiring ------------------------------------------------------------------------------------------------------

def test_pipeline_attaches_a_json_safe_plan_to_every_record():
    now = datetime(2025, 11, 3, tzinfo=timezone.utc)
    met = {k: model.ventilation_stats([120.0] * 48, [1.0] * 48) for k in CITIES}
    recs = pipeline.build_records([], sources.synthetic_wind(), {}, now, met=met)
    for key, rec in recs.items():
        assert set(rec["school"]) == {"status", "headline", "activities", "best_time", "smoke_window", "notice"}, key
    assert recs["delhi"]["school"]["status"] == "limit" and recs["delhi"]["school"]["best_time"]
    assert recs["jaipur"]["school"]["status"] == "ok" and recs["jaipur"]["school"]["best_time"] is None    # unvalidated city
    json.dumps(recs)


def test_shipped_mock_data_includes_the_school_plan():
    mock = json.loads((ROOT / "frontend" / "mock.json").read_text(encoding="utf-8"))
    for r in mock["risk"]:
        assert r["school"]["status"] in RANK and len(r["school"]["activities"]) == 6
    delhi = next(r for r in mock["risk"] if r["city"] == "delhi")
    assert delhi["school"]["status"] == "limit" and delhi["school"]["smoke_window"]["en"].startswith("Smoke expected roughly 6-23")
