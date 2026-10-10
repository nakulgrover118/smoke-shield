import json
from datetime import datetime, timezone

import backtest as bt
import build_static_mask as bsm
import pytest
from common import filters, pipeline, sources
from common.cities import CITIES, URBAN_EXCLUSIONS
from common.geo import advance

DELHI = CITIES["delhi"]


def fire(lat, lon, frp=20.0):
    return {"lat": lat, "lon": lon, "frp": frp}


# ---- urban exclusion -----------------------------------------------------------------------

def test_in_urban_cores_but_not_outskirts_farmland():
    assert filters.in_urban(DELHI["lat"], DELHI["lon"])
    assert filters.in_urban(CITIES["ludhiana"]["lat"] + 0.05, CITIES["ludhiana"]["lon"])
    assert not filters.in_urban(28.85, 77.09)             # Narela/Bawana farmland belt, ~30 km from the centre
    assert not filters.in_urban(30.2, 75.4)               # open Punjab countryside


def test_every_exclusion_has_sane_values():
    for name, lat, lon, r in URBAN_EXCLUSIONS:
        assert 26 <= lat <= 33 and 73 <= lon <= 79 and 3 <= r <= 25, name


# ---- static mask ---------------------------------------------------------------------------

def test_static_mask_matches_cell_and_neighbours_only():
    m = filters.StaticMask(0.02, [[1500, 3800]])          # cell covering lat 30.00-30.02, lon 76.00-76.02
    assert m.contains(30.01, 76.01)
    assert m.contains(30.03, 76.01)                       # adjacent cell: geolocation jitter allowance
    assert not m.contains(30.10, 76.01)
    assert len(m) == 1


def test_build_mask_needs_repeat_days_not_repeat_detections():
    spot = fire(30.01, 76.01)
    by_day = {f"2025-01-0{d}": [spot, spot, spot] for d in (1, 2, 3)}      # 9 detections but only 3 distinct days
    assert filters.build_mask(by_day, 0.02, min_days=4) == []
    by_day["2025-01-04"] = [spot]
    assert filters.build_mask(by_day, 0.02, min_days=4) == [[1500, 3800]]
    by_day["2025-01-05"] = [fire(31.5, 75.5)]                              # one-off field fire elsewhere stays unmasked
    assert len(filters.build_mask(by_day, 0.02, min_days=4)) == 1


# ---- filter_fires --------------------------------------------------------------------------

def test_filter_modes_and_stats():
    mask = filters.StaticMask(0.02, [[1500, 3800]])
    fires = [fire(DELHI["lat"], DELHI["lon"]), fire(30.01, 76.01), fire(30.5, 75.4)]
    none_kept, s = filters.filter_fires(fires, "none")
    assert len(none_kept) == 3 and s["kept"] == 3
    urban_kept, s = filters.filter_fires(fires, "urban", mask)
    assert len(urban_kept) == 2 and s["urban"] == 1 and s["static"] == 0
    static_kept, s = filters.filter_fires(fires, "static", mask)
    assert len(static_kept) == 2 and s["static"] == 1 and s["urban"] == 0
    all_kept, s = filters.filter_fires(fires, "all", mask)
    assert all_kept == [fires[2]] and (s["raw"], s["urban"], s["static"], s["kept"]) == (3, 1, 1, 1)


def test_filter_rejects_unknown_mode_and_missing_mask(monkeypatch):
    with pytest.raises(ValueError):
        filters.filter_fires([], "bogus")
    monkeypatch.setattr(filters, "load_static_mask", lambda path=None: None)
    with pytest.raises(FileNotFoundError):
        filters.filter_fires([fire(30.0, 76.0)], "static")
    kept, s = filters.filter_fires([fire(DELHI["lat"], DELHI["lon"]), fire(30.0, 76.0)], "all")   # degrades to urban-only
    assert len(kept) == 1 and s["static_mask"] is False


def test_shipped_mask_loads_and_is_plausible():
    m = filters.load_static_mask()
    assert m is not None and 10 < len(m) < 20000
    assert m.meta["cell_deg"] == filters.MASK_CELL_DEG


# ---- effect on the model -------------------------------------------------------------------

def test_filter_removes_a_waste_fire_that_would_have_hit_delhi():
    now = datetime(2025, 11, 3, 0, tzinfo=timezone.utc)
    wind = sources.synthetic_wind(315.0, 15.0)
    crop = fire(*advance(DELHI["lat"], DELHI["lon"], 315.0, 150.0), frp=50.0)   # genuine upwind crop fire
    landfill = fire(DELHI["lat"] + 0.05, DELHI["lon"] + 0.05, frp=300.0)        # inside the Delhi urban core
    raw = pipeline.build_records([crop, landfill], wind, {}, now, {"delhi": DELHI}, fire_filter="none")["delhi"]
    cleaned = pipeline.build_records([crop, landfill], wind, {}, now, {"delhi": DELHI}, fire_filter="all")["delhi"]
    assert raw["arrival_hour"] == 1 and raw["smoke_load"] > cleaned["smoke_load"] * 3
    assert cleaned["arrival_hour"] == 7                  # only the real crop fire remains
    assert (cleaned["fires_total"], cleaned["fires_used"]) == (2, 1)


# ---- build_static_mask script --------------------------------------------------------------

FIRMS_HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"


def test_parse_periods_and_detections_by_day():
    assert bsm.parse_periods("2025-01-01:2025-01-12,2025-07-01:2025-07-05")[1].__len__() == 2
    text = FIRMS_HEADER + "30.01,76.01,330,0.4,0.4,2025-01-01,0100,N,VIIRS,n,2.0NRT,300,5.0,N\n" \
                          "30.02,76.02,330,0.4,0.4,2025-01-02,0100,N,VIIRS,l,2.0NRT,300,5.0,N\nbad,row\n"
    assert bsm.detections_by_day(text) == {"2025-01-01": [{"lat": 30.01, "lon": 76.01}]}   # low confidence + garbage dropped


def test_build_static_mask_script_end_to_end(monkeypatch, tmp_path):
    urls = []

    def fake_http(url, secret=None, tries=4):
        urls.append(url)
        start = url.rsplit("/", 1)[1]
        day = int(start[-2:])
        return FIRMS_HEADER + f"30.01,76.01,330,0.4,0.4,2025-01-{day:02d},0100,N,VIIRS,n,2.0NRT,300,5.0,N\n"

    monkeypatch.setattr(bsm, "http_get", fake_http)
    monkeypatch.setattr(bsm.time, "sleep", lambda s: None)
    out = tmp_path / "mask.json"
    assert bsm.main(["--firms-key", "K", "--periods", "2025-01-01:2025-01-12", "--min-days", "3",
                     "--cache-dir", str(tmp_path / "c"), "--out", str(out)]) == 0
    assert [u.split("/")[-2] + "@" + u.split("/")[-1] for u in urls] == ["5@2025-01-01", "5@2025-01-06", "2@2025-01-11"]
    data = json.loads(out.read_text())
    assert data["cells"] == [[1500, 3800]] and data["cell_deg"] == 0.02 and "K" not in out.read_text()
    with pytest.raises(SystemExit):
        bsm.main(["--firms-key", "", "--out", str(out)])


# ---- back-test integration -----------------------------------------------------------------

def test_backtest_reports_filter_and_compares_modes(monkeypatch, tmp_path, sample_fires_csv):
    from test_backtest import _fake_http
    monkeypatch.setattr(bt, "http_get", _fake_http(sample_fires_csv, []))
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    args = bt.parse_args(["--start", "2025-11-01", "--end", "2025-11-06", "--firms-key", "K", "--filter", "all",
                          "--compare-filters", "--cache-dir", str(tmp_path)])
    rep = bt.run(args)
    assert rep["filter"]["mode"] == "all" and rep["filter"]["kept"] <= rep["filter"]["raw"] == 6 * 17
    modes = [c["mode"] for c in rep["filter_compare"]]
    assert modes == ["none", "urban", "static", "all"]
    assert rep["filter_compare"][0]["kept_frac"] == pytest.approx(1.0)
    rep.pop("_rows")
    bt.print_report(rep)


def test_demo_defaults_to_no_filter():
    assert bt.run(bt.parse_args(["--demo"]))["filter"]["mode"] == "none"
