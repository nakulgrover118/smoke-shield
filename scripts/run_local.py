"""Run the whole pipeline on your machine - no AWS account needed.

  python scripts/run_local.py                      # offline: sample fires + synthetic NW wind
  python scripts/run_local.py --live               # real FIRMS + Open-Meteo (needs FIRMS_MAP_KEY env var)
  python scripts/run_local.py --write-mock         # also writes frontend/mock.json for the map UI
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))
sys.path.insert(0, str(ROOT / "functions" / "advisory"))

import os  # noqa: E402

from common import pipeline, sources  # noqa: E402
from common.cities import CITIES  # noqa: E402
from common.guidance import fallback_advisory  # noqa: E402
from common.model import ventilation_stats  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use real FIRMS + Open-Meteo data")
    ap.add_argument("--agent", action="store_true", help="also call the Strands/Bedrock agent (needs AWS creds + model access)")
    ap.add_argument("--write-mock", action="store_true", help="write frontend/mock.json")
    ap.add_argument("--wind-from", type=float, default=315.0, help="offline wind direction (deg, where it blows FROM)")
    ap.add_argument("--wind-kmh", type=float, default=15.0, help="offline wind speed")
    args = ap.parse_args()

    now = sources.utcnow()
    if args.live:
        fires = sources.parse_fires(sources.fetch_fires_csv(os.environ.get("FIRMS_MAP_KEY")), now)
        wind = sources.parse_wind(sources.fetch_wind_json(), now)
        aq = sources.parse_aq(sources.fetch_aq_json(CITIES), CITIES, now)
        met = sources.parse_ventilation(sources.fetch_met_json(CITIES), CITIES, now)
    else:
        fires = sources.parse_fires((ROOT / "samples" / "fires_sample.csv").read_text())
        wind = sources.synthetic_wind(args.wind_from, args.wind_kmh)
        aq = {}
        # Made-up boundary-layer height (m) and wind (m/s) so the demo shows all three air-mixing labels.
        demo_met = {"delhi": (150, 1.0), "gurugram": (200, 1.0), "chandigarh": (300, 1.5), "ludhiana": (400, 1.5), "jaipur": (400, 1.5)}
        met = {k: ventilation_stats([blh] * 48, [ws] * 48) for k, (blh, ws) in demo_met.items()}

    records = pipeline.build_records(fires, wind, aq, now, met=met)
    print(f"{len(fires)} fire detections -> {len(records)} cities\n")
    advisories = {}
    for key, rec in records.items():
        arr = f"{rec['arrival_hour']}h (window {rec['window_start_hour']}-{rec['window_end_hour']}h)" \
            if rec["arrival_hour"] else "-"
        print(f"{rec['name']:<11} {rec['risk_level']:<9} load={rec['smoke_load']:>7}  "
              f"upwind={rec['fire_cells_upwind']}/{rec['fire_cells_total']}  arrival={arr}  air mixing={rec['stagnation']}")
        advisories[key] = {}
        for lang in ("en", "hi"):
            name = rec["name_hi"] if lang == "hi" else rec["name"]
            text, source = fallback_advisory(name, rec, lang), "fallback"
            if args.agent:
                from advisory_agent import generate_advisory
                text, source = generate_advisory(name, rec, lang)
            advisories[key][lang] = {"city": key, "lang": lang, "risk_level": rec["risk_level"], "advisory": text,
                                     "source": source, "risk_generated_at": rec["generated_at"]}

    if args.write_mock:
        out = ROOT / "frontend" / "mock.json"
        out.write_text(json.dumps({"risk": list(records.values()), "advisory": advisories}, indent=1))
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
