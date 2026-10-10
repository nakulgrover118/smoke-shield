"""Strands agent (open source, AWS) that turns a deterministic risk record into a school advisory.

The numbers come from the model and the actions come from guidance.py - the LLM only decides
how to say it. Imports of `strands` are lazy so tests and the fallback path work without it.
"""
import json
import os

from common.guidance import fallback_advisory, guidance_for, stagnation_applies, stagnation_guidance  # noqa: F401

LANGS = {"en": "English", "hi": "Hindi (Devanagari script)"}

SYSTEM_PROMPT = """You write short smoke advisories for school administrators in India.
Rules:
- Call get_smoke_forecast first, then get_school_guidance with the risk level you received.
- If get_smoke_forecast returns a non-null "stagnation_advice" label, also call get_stagnation_guidance with it and add that note and its action
  as one extra sentence and one extra bullet. If "stagnation_advice" is null, say nothing about air mixing.
- Use ONLY numbers from get_smoke_forecast. Never invent AQI values, times or counts.
- Choose actions ONLY from the guidance tools; you may reword them but not add new health claims.
- Times are hours from now. Say them as 'in about N hours' and give the window as a range.
- If risk is LOW, say so plainly and keep it to two sentences (plus the air-mixing note if there is one).
- Max 150 words. Format: one headline line, one timing line, then 2-4 bullet actions.
- End with: 'Forecast estimate, not medical advice.'
- Write in the requested language."""


def _build_agent(risk):
    from strands import Agent, tool
    from strands.models import BedrockModel

    @tool
    def get_smoke_forecast() -> str:
        """Return the latest smoke-arrival forecast for the city as JSON (hours are relative to now)."""
        keep = ("name", "risk_level", "arrival_hour", "window_start_hour", "window_end_hour", "peak_hour",
                "fire_cells_upwind", "fire_cells_total", "pm25_now", "pm25_max_24h", "generated_at")
        out = {k: risk.get(k) for k in keep}
        # only cities where the label was validated against measured PM2.5 get air-mixing advice
        out["stagnation_advice"] = risk["stagnation"] if stagnation_applies(risk) else None
        return json.dumps(out)

    @tool
    def get_school_guidance(level: str) -> str:
        """Return the approved school actions for a risk level (LOW, MODERATE, HIGH or SEVERE)."""
        return json.dumps(guidance_for(level.upper()))

    @tool
    def get_stagnation_guidance(label: str) -> str:
        """Return the approved note and action for an air-mixing label from get_smoke_forecast (currently only POOR has advice)."""
        return json.dumps(stagnation_guidance(label.upper()))

    kwargs = {}
    if os.environ.get("BEDROCK_MODEL_ID"):
        kwargs["model_id"] = os.environ["BEDROCK_MODEL_ID"]
    if os.environ.get("BEDROCK_REGION"):
        kwargs["region_name"] = os.environ["BEDROCK_REGION"]
    model = BedrockModel(temperature=0.2, **kwargs)
    return Agent(model=model, system_prompt=SYSTEM_PROMPT,
                 tools=[get_smoke_forecast, get_school_guidance, get_stagnation_guidance], callback_handler=None)


def generate_advisory(city_name, risk, lang="en"):
    """-> (text, source) where source is 'agent' or 'fallback'. Never raises."""
    if os.environ.get("DISABLE_AGENT") == "1":
        return fallback_advisory(city_name, risk, lang), "fallback"
    try:
        agent = _build_agent(risk)
        result = agent(f"Write the advisory for {city_name} in {LANGS.get(lang, 'English')}.")
        text = str(result).strip()
        if text:
            return text, "agent"
    except Exception as exc:  # no model access, throttling, missing package... demo must keep working
        print(f"agent failed, using fallback: {exc!r}")
    return fallback_advisory(city_name, risk, lang), "fallback"
