"""Build the static-source mask used by the fire filter.

Crop-residue fires are transient: a field burns once. Landfills, brick kilns and industry burn again and again.
So we pull FIRMS detections from months with (almost) no crop burning, and flag every ~2 km cell that has a detection
on several different days. Those cells are then ignored when counting crop fires.

  python scripts/build_static_mask.py                       # needs FIRMS_MAP_KEY
  python scripts/build_static_mask.py --periods 2025-01-01:2025-03-31,2025-07-01:2025-09-30 --min-days 4

Default periods are Jan-Mar and Jul-Sep: after the wheat-residue burn (Apr-May) and before paddy (mid-Oct to Nov).
FIRMS' archive allows at most 5 days per request, so this is ~40 requests (cached under .cache/ for re-runs).
Review the printed top cells (they should be landfills / industrial areas) before committing the output.
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))

from backtest import cached_text, http_get  # noqa: E402  (same folder)
from common import filters  # noqa: E402
from common.cities import FIRE_BBOX  # noqa: E402

URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}/{start}"


def parse_periods(text):
    out = []
    for part in text.split(","):
        a, b = part.split(":")
        out.append((datetime.strptime(a, "%Y-%m-%d").date(), datetime.strptime(b, "%Y-%m-%d").date()))
    return out


def fetch_window(key, source, start, days, cache):
    url = URL.format(key=key, source=source, bbox=",".join(str(x) for x in FIRE_BBOX), days=days, start=start.isoformat())

    def fetch():
        text = http_get(url, key)
        if not text.lstrip().startswith("latitude"):
            raise RuntimeError(f"FIRMS returned an unexpected body for {start}: {text[:100]!r}")
        time.sleep(0.5)
        return text
    return cached_text(cache / f"firms{days}_{source}_{start}.csv", fetch)


def detections_by_day(text):
    """-> {acq_date: [{'lat','lon'}]}, dropping low-confidence detections like sources.parse_fires does."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            if str(row.get("confidence", "")).strip().lower().startswith("l"):
                continue
            point = {"lat": float(row["latitude"]), "lon": float(row["longitude"])}   # parse first: bad rows must not create a day
            day = row["acq_date"]
            if not day:
                continue
            out.setdefault(day, []).append(point)
        except (KeyError, ValueError, TypeError):
            continue
    return out


def collect(key, source, periods, cache):
    by_day = {}
    for start, end in periods:
        s = start
        while s <= end:
            days = min(5, (end - s).days + 1)
            print(f"  {s} (+{days}d)", file=sys.stderr)
            for day, fires in detections_by_day(fetch_window(key, source, s, days, cache)).items():
                by_day.setdefault(day, []).extend(fires)
            s += timedelta(days=days)
    return by_day


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--firms-key", default=os.environ.get("FIRMS_MAP_KEY"))
    ap.add_argument("--firms-source", default="VIIRS_SNPP_SP")
    ap.add_argument("--periods", default="2025-01-01:2025-03-31,2025-07-01:2025-09-30")
    ap.add_argument("--cell-deg", type=float, default=filters.MASK_CELL_DEG)
    ap.add_argument("--min-days", type=int, default=filters.MASK_MIN_DAYS)
    ap.add_argument("--cache-dir", default=str(ROOT / ".cache" / "backtest"))
    ap.add_argument("--out", default=str(filters.STATIC_MASK_PATH))
    args = ap.parse_args(argv)
    if not args.firms_key:
        raise SystemExit("Need a FIRMS key: --firms-key or FIRMS_MAP_KEY")

    periods = parse_periods(args.periods)
    by_day = collect(args.firms_key, args.firms_source, periods, Path(args.cache_dir))
    n_det = sum(len(v) for v in by_day.values())
    if not n_det:
        raise SystemExit("no detections found; check the periods and key")
    cells = filters.build_mask(by_day, args.cell_deg, args.min_days)
    mask = filters.StaticMask(args.cell_deg, cells)
    inside = sum(mask.contains(f["lat"], f["lon"]) for fs in by_day.values() for f in fs)

    # sanity view: the most persistent cells (should be landfills / industrial areas / kilns)
    days_per_cell = {}
    for day, fs in by_day.items():
        for f in fs:
            c = (int(f["lat"] // args.cell_deg), int(f["lon"] // args.cell_deg))
            days_per_cell.setdefault(c, set()).add(day)
    print(f"\n{n_det} off-season detections on {len(by_day)} days -> {len(cells)} static-source cells "
          f"(>= {args.min_days} distinct days); {inside / n_det:.0%} of off-season detections fall inside the mask")
    print("most persistent cells (lat, lon, days with a detection):")
    for c, days in sorted(days_per_cell.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"  {(c[0] + 0.5) * args.cell_deg:.3f}, {(c[1] + 0.5) * args.cell_deg:.3f}   {len(days)} days")

    payload = {"cell_deg": args.cell_deg, "min_days": args.min_days, "source": args.firms_source,
               "periods": args.periods, "built": date.today().isoformat(), "n_detections": n_det, "cells": cells}
    Path(args.out).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out} ({Path(args.out).stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
