"""Keep only detections that plausibly are crop-residue fires.

Raw VIIRS detections in the region include waste dumps, brick kilns, industry and cooking fires. Two cheap filters:

  urban   drop detections inside the urban cores in cities.URBAN_EXCLUSIONS.
  static  drop detections on locations that burn repeatedly outside the crop-burning seasons. Crop fires are transient (a
          field burns once); landfills and kilns are not. The mask is built by scripts/build_static_mask.py from FIRMS
          history and shipped as static_sources.json next to this file.

Neither filter is land cover: some crop fires near cities are lost and some non-crop fires slip through.
Modes: none | urban | static | all.
"""
import json
import logging
import math
from functools import lru_cache
from pathlib import Path

from .cities import URBAN_EXCLUSIONS
from .geo import haversine_km

log = logging.getLogger(__name__)
MODES = ("none", "urban", "static", "all")
STATIC_MASK_PATH = Path(__file__).with_name("static_sources.json")
MASK_CELL_DEG = 0.02          # ~2 km
MASK_MIN_DAYS = 4             # distinct off-season days with a detection before a cell counts as a static source


class StaticMask:
    def __init__(self, cell_deg, cells, meta=None):
        self.cell_deg = cell_deg
        self.cells = {tuple(c) for c in cells}
        self.meta = meta or {}

    def contains(self, lat, lon):
        """True if the detection falls in, or next to, a static-source cell (VIIRS geolocation jitters by a few hundred m)."""
        i, j = math.floor(lat / self.cell_deg), math.floor(lon / self.cell_deg)
        return any((i + di, j + dj) in self.cells for di in (-1, 0, 1) for dj in (-1, 0, 1))

    def __len__(self):
        return len(self.cells)


@lru_cache(maxsize=4)
def _load(path):
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return StaticMask(data["cell_deg"], data["cells"], {k: v for k, v in data.items() if k != "cells"})


def load_static_mask(path=None):
    """The shipped mask, or None if it has not been built."""
    return _load(str(path or STATIC_MASK_PATH))


def in_urban(lat, lon, centers=None):
    for _, clat, clon, radius in (centers if centers is not None else URBAN_EXCLUSIONS):
        # cheap box test first: 1 degree of latitude is ~111 km
        if abs(lat - clat) <= radius / 100.0 and haversine_km(lat, lon, clat, clon) <= radius:
            return True
    return False


def filter_fires(fires, mode="all", mask=None, centers=None):
    """-> (kept_fires, stats). `fires` are {'lat','lon','frp'} dicts."""
    if mode not in MODES:
        raise ValueError(f"fire filter mode must be one of {MODES}, got {mode!r}")
    use_urban, use_static = mode in ("urban", "all"), mode in ("static", "all")
    if use_static and mask is None:
        mask = load_static_mask()
        if mask is None:
            if mode == "static":
                raise FileNotFoundError(f"{STATIC_MASK_PATH.name} not found: run scripts/build_static_mask.py")
            log.warning("static-source mask not built; filtering urban cores only")
    stats = {"mode": mode, "raw": 0, "urban": 0, "static": 0, "kept": 0, "static_mask": mask is not None and use_static}
    kept = []
    for f in fires:
        stats["raw"] += 1
        if use_urban and in_urban(f["lat"], f["lon"], centers):
            stats["urban"] += 1
        elif use_static and mask is not None and mask.contains(f["lat"], f["lon"]):
            stats["static"] += 1
        else:
            kept.append(f)
    stats["kept"] = len(kept)
    return kept, stats


def build_mask(fires_by_day, cell_deg=MASK_CELL_DEG, min_days=MASK_MIN_DAYS):
    """fires_by_day: {day: [fire dicts]} from the NON-burning months -> sorted [[i, j], ...] of repeat-burn cells."""
    days_per_cell = {}
    for day, fires in fires_by_day.items():
        for f in fires:
            cell = (math.floor(f["lat"] / cell_deg), math.floor(f["lon"] / cell_deg))
            days_per_cell.setdefault(cell, set()).add(day)
    return sorted([list(c) for c, days in days_per_cell.items() if len(days) >= min_days])
