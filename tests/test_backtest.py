import json
import random
from datetime import datetime, timedelta, timezone

import backtest as bt
import pytest
from common import model, sources
from common.cities import CITIES
from common.geo import advance
from common.model import ModelParams

UTC = timezone.utc


# ---- statistics ---------------------------------------------------------------------------

def test_spearman_known_values():
    assert bt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert bt.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert bt.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8)
    assert bt.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None      # constant input has no rank correlation
    assert bt.spearman([1, 2], [1, 2]) is None                  # too few points


def test_rankdata_averages_ties():
    assert bt.rankdata([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_auc_known_values():
    assert bt.auc([1, 2, 3, 4], [False, False, True, True]) == pytest.approx(1.0)
    assert bt.auc([4, 3, 2, 1], [False, False, True, True]) == pytest.approx(0.0)
    assert bt.auc([1, 1, 1, 1], [False, False, True, True]) == pytest.approx(0.5)
    assert bt.auc([1, 2], [True, True]) is None


def test_prf_and_best_threshold():
    r = bt.prf([True, True, False, False], [True, False, True, False])
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1) and r["f1"] == pytest.approx(0.5)
    loads = [0, 0, 50, 120, 300, 800]
    labels = [False, False, False, True, True, True]
    thr, f1 = bt.best_threshold(loads, labels)
    assert thr == 120 and f1 == pytest.approx(1.0)
    assert bt.best_threshold(loads, [False] * 6) is None


def _rows(loads, obs):
    t0 = datetime(2025, 11, 1, tzinfo=UTC)
    return [{"issue": t0 + timedelta(days=i), "city": "delhi", "level": "LOW", "load": l, "arrival_hour": None,
             "peak_hour": None, "frp_total": 100.0, "persistence": 100.0, "obs": o, "obs_peak_hour": None,
             "inv_vi": None, "vi_mean": None, "smoke_index": None}
            for i, (l, o) in enumerate(zip(loads, obs))]


def test_threshold_suggestion_refuses_to_fit_when_alerting_every_day_is_as_good():
    loads = [float(i) for i in range(40)]
    always_on = bt.summarize(_rows(loads, [300.0] * 40), 150.0, [100.0, 150.0, 250.0])   # every day is an event
    assert always_on["suggested_thresholds"] == [None, None, None]
    informative = [20.0 if l < 20 else 400.0 for l in loads]                              # events exactly when load >= 20
    s = bt.summarize(_rows(loads, informative), 150.0, [100.0, 150.0, 250.0])["suggested_thresholds"]
    assert s[1] == 20.0
    noise = [400.0 if i % 3 else 20.0 for i in range(40)]                                 # ~2/3 events, unrelated to load
    assert bt.summarize(_rows(loads, noise), 150.0, [150.0])["suggested_thresholds"] == [None]


def test_threshold_suggestion_is_not_fooled_by_pooling_cities():
    """Simpson's paradox: pooled, high load 'predicts' events only because the dirty city is also the high-load city."""
    t0 = datetime(2025, 11, 1, tzinfo=UTC)
    rows = []
    for i in range(30):                       # city A: low loads, clean air; within the city, load is unrelated to PM2.5
        rows.append({**_rows([1.0 + (i % 5)], [40.0 + (i * 7) % 30])[0], "city": "a", "issue": t0 + timedelta(days=i)})
    for i in range(30):                       # city B: high loads, dirty air; again unrelated within the city
        rows.append({**_rows([100.0 + (i % 5)], [300.0 + (i * 7) % 30])[0], "city": "b", "issue": t0 + timedelta(days=i)})
    assert bt.auc([r["load"] for r in rows], [r["obs"] >= 150 for r in rows]) > 0.95   # pooled AUC looks perfect...
    assert bt.summarize(rows, 150.0, [150.0])["suggested_thresholds"] == [None]        # ...but it must be refused


def test_partial_spearman_removes_a_shared_cause():
    rng = random.Random(1)
    z = [rng.random() for _ in range(300)]
    x = [zi + 0.3 * rng.random() for zi in z]            # x and y both just follow z...
    y = [zi + 0.3 * rng.random() for zi in z]
    assert bt.spearman(x, y) > 0.7
    assert abs(bt.partial_spearman(x, y, z)) < 0.2       # ...so nothing is left once z is removed
    y2 = [zi + xi + 0.3 * rng.random() for zi, xi in zip(z, x)]   # y2 genuinely depends on x as well
    assert bt.partial_spearman(x, y2, z) > 0.5
    assert bt.partial_spearman([1, 2], [1, 2], [1, 2]) is None


def test_block_bootstrap_ci_brackets_strong_signal():
    xs = list(range(40))
    ys = [x + (3 if x % 5 == 0 else 0) for x in xs]
    lo, hi = bt.block_bootstrap_ci(xs, ys, bt.spearman)
    assert 0.9 < lo <= hi <= 1.0
    assert bt.block_bootstrap_ci([1, 2, 3], [1, 2, 3], bt.spearman) is None


# ---- truth --------------------------------------------------------------------------------

def test_parse_ts_handles_offsets_and_formats():
    assert bt.parse_ts("2025-11-03T12:00:00Z") == datetime(2025, 11, 3, 12, tzinfo=UTC)
    assert bt.parse_ts("2025-11-03 12:00", utc_offset_h=5.5) == datetime(2025, 11, 3, 6, 30, tzinfo=UTC)
    assert bt.parse_ts("03-11-2025 12:00") == datetime(2025, 11, 3, 12, tzinfo=UTC)
    assert bt.parse_ts("2025-11-03T12:00:00+05:30") == datetime(2025, 11, 3, 6, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        bt.parse_ts("yesterday")


def test_load_truth_csv(tmp_path):
    f = tmp_path / "pm.csv"
    f.write_text("City,Timestamp,PM2.5\nDelhi,2025-11-03 06:00,200\ndelhi,2025-11-03 07:00,220\n"
                 "Atlantis,2025-11-03 06:00,50\nDelhi,2025-11-03 08:00,abc\nDelhi,2025-11-03 09:00,-5\n",
                 encoding="utf-8")
    truth = bt.load_truth_csv(f, utc_offset_h=5.5)
    start = datetime(2025, 11, 3, 0, 0, tzinfo=UTC)
    pts = truth.window("delhi", start, start + timedelta(hours=2))
    assert [v for _, v in pts] == [200.0, 220.0]
    assert truth.window("atlantis", start, start + timedelta(hours=2)) is None


def test_truth_window_requires_enough_coverage():
    t0 = datetime(2025, 11, 1, tzinfo=UTC)
    hourly = bt.Truth({"delhi": [(t0 + timedelta(hours=i), 100.0) for i in range(48)]})
    assert hourly.window("delhi", t0, t0 + timedelta(hours=48)) is not None
    assert hourly.window("delhi", t0, t0 + timedelta(hours=96)) is not None          # exactly half present
    assert hourly.window("delhi", t0, t0 + timedelta(hours=200)) is None             # mostly missing
    daily = bt.Truth({"delhi": [(t0 + timedelta(days=i), 100.0) for i in range(5)]})
    assert daily.spacing("delhi") == 24.0
    assert daily.window("delhi", t0, t0 + timedelta(hours=48)) is not None           # 1 daily value is enough


# ---- wind archive --------------------------------------------------------------------------

def test_wind_archive_slices_from_issue_time():
    pts = [(28.0, 77.0)]
    times = [f"2025-11-03T{h:02d}:00" for h in range(24)]
    payload = {"hourly": {"time": times, "wind_speed_10m": list(range(24)), "wind_direction_10m": [300] * 24}}
    arch = bt.WindArchive()
    arch.add(payload, pts)
    wf = arch.field_at(datetime(2025, 11, 3, 5, tzinfo=UTC), hours=10)
    assert wf.points[pts[0]][0] == (5, 300) and len(wf.points[pts[0]]) == 10
    assert arch.field_at(datetime(2025, 11, 9, tzinfo=UTC)) is None   # outside the archive


# ---- model refactor the back-test depends on ----------------------------------------------

def test_params_change_the_prediction_and_shared_paths_match():
    delhi = CITIES["delhi"]
    lat, lon = advance(delhi["lat"], delhi["lon"], 315.0, 150.0)   # 150 km upwind of Delhi
    cell = model.FireCell(lat, lon, 100.0, 5)
    wind = sources.synthetic_wind(315.0, 15.0)
    base = model.assess_city(delhi, [cell], wind)
    assert base["arrival_hour"] == 7 and base["smoke_load"] > 0
    shared = model.assess_city(delhi, [cell], wind, paths=model.compute_paths([cell], wind))
    assert base == shared
    slow = model.assess_city(delhi, [cell], wind, params=ModelParams(wind_scale=0.4))
    assert slow["arrival_hour"] is None or slow["arrival_hour"] > base["arrival_hour"]
    tight = model.assess_city(delhi, [cell], wind, params=ModelParams(radius_km=5.0))
    assert tight["arrival_hour"] > base["arrival_hour"]
    quick_decay = model.assess_city(delhi, [cell], wind, params=ModelParams(decay_h=6.0))
    assert quick_decay["smoke_load"] < base["smoke_load"]


# ---- end to end on the synthetic season ----------------------------------------------------

@pytest.fixture(scope="module")
def demo_report():
    rep = bt.run(bt.parse_args(["--demo"]))
    return rep


def test_demo_run_shows_model_beats_fire_counts(demo_report):
    rep = demo_report
    assert rep["n_rows"] > 150
    assert rep["mean_rho"] > 0.4                       # truth was built from the model's own output, so it must find it
    assert rep["mean_rho"] > rep["mean_rho_frp"]       # ...and wind must add value over raw fire counts
    levels = [rep["by_level"][lv] for lv in model.LEVELS if rep["by_level"][lv]["n"] >= 5]
    means = [d["mean_obs"] for d in levels]
    assert means == sorted(means)                      # observed PM2.5 rises with predicted level


def test_demo_report_is_json_serialisable_and_printable(demo_report, capsys):
    rep = dict(demo_report)
    rows = rep.pop("_rows")
    bt.print_report(rep)
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out and "Suggested constants" in out
    json.dumps(rep, default=str)
    assert rows[0]["city"] in CITIES


@pytest.mark.parametrize("rho, frp, delta, expected", [
    (-0.19, -0.54, -0.10, "NO demonstrable skill"),          # the real 2025 run: beating a worse negative is not skill
    (-0.16, -0.22, 0.30, "MIXED"),                            # tuned 2025 run: only 'changes' positive, levels negative
    (0.40, 0.38, 0.30, "does NOT clearly beat fire counts"),
    (0.45, 0.10, 0.02, "possibly just seasonal trend"),
    (0.45, 0.10, 0.30, "adds value over fire counts alone and predicts changes"),
])
def test_verdict_never_calls_negative_correlation_a_win(demo_report, capsys, rho, frp, delta, expected):
    rep = {k: v for k, v in demo_report.items() if k != "_rows"}
    rep.update(mean_rho=rho, mean_rho_frp=frp, mean_rho_delta=delta)
    bt.print_report(rep)
    assert expected in capsys.readouterr().out


def test_demo_weather_section(demo_report, capsys):
    rep = {k: v for k, v in demo_report.items() if k != "_rows"}
    assert rep["n_met_rows"] > 150
    assert rep["mean_rho_vent"] > 0.3                    # the synthetic truth is scaled by stagnation, so ventilation must show it
    assert rep["mean_rho_partial"] > 0.15                # ...and smoke must survive controlling for it
    bt.print_report(rep)
    out = capsys.readouterr().out
    assert "Does smoke add anything beyond the weather?" in out and "smoke carries information beyond ventilation" in out


def test_one_city_cannot_carry_the_verdict(demo_report, capsys):
    """Regression for the 2019 tuned run: Jaipur alone (rho 0.69) pulled the mean over the line."""
    rep = {k: v for k, v in demo_report.items() if k != "_rows"}
    rep["cities"] = {k: dict(v) for k, v in rep["cities"].items()}
    for i, c in enumerate(rep["cities"].values()):
        c["rho"] = c["rho_partial"] = 0.8 if i == 0 else 0.0
    rep.update(mean_rho=0.4, mean_rho_frp=0.0, mean_rho_delta=0.4, mean_rho_partial=0.4, mean_rho_index=0.5, mean_rho_vent=0.2)
    bt.print_report(rep)
    out = capsys.readouterr().out
    assert "one city is probably driving the mean" in out and "likely one city driving the mean" in out
    assert "adds value over fire counts alone" not in out and "smoke carries information beyond ventilation" not in out


def test_weather_verdict_when_smoke_adds_nothing(demo_report, capsys):
    rep = {k: v for k, v in demo_report.items() if k != "_rows"}
    rep.update(mean_rho_partial=0.02, mean_rho_index=0.30, mean_rho_vent=0.31)
    bt.print_report(rep)
    out = capsys.readouterr().out
    assert "smoke load explains little" in out and "does NOT beat ventilation alone" in out


def test_tune_can_optimise_the_partial_objective():
    cases, truth = bt.demo_data(days=30)
    cities = {"delhi": CITIES["delhi"], "chandigarh": CITIES["chandigarh"]}
    ranked = bt.tune(cases, truth, cities, model.LOAD_THRESHOLDS, scales=[1.0], radii=[50.0], decays=[24.0], objective="partial")
    assert ranked[0][0] is not None and ranked[0][0] > 0


def test_demo_predicts_changes_not_just_levels(demo_report):
    assert demo_report["mean_rho_delta"] is not None and demo_report["mean_rho_delta"] > 0.15


def test_main_writes_outputs(tmp_path, capsys):
    out, csv_path = tmp_path / "r.json", tmp_path / "rows.csv"
    assert bt.main(["--demo", "--cities", "delhi,ludhiana", "--out", str(out), "--csv", str(csv_path)]) == 0
    assert json.loads(out.read_text())["cities"].keys() == {"delhi", "ludhiana"}
    assert csv_path.read_text().splitlines()[0].startswith("issue,city,level,load")


def test_tune_does_not_get_worse_than_default_on_train():
    cases, truth = bt.demo_data(days=30)
    cities = {"delhi": CITIES["delhi"], "chandigarh": CITIES["chandigarh"]}
    ranked = bt.tune(cases, truth, cities, model.LOAD_THRESHOLDS, scales=[0.75, 1.0], radii=[50.0], decays=[24.0])
    default = next(s for s, p in ranked if p.wind_scale == 1.0)
    assert ranked[0][0] >= default


def _fake_http(sample_fires_csv, calls):
    """Stand-in for backtest.http_get that answers FIRMS / ERA5 / CAMS from the URL alone."""
    def hourly(start, end):
        d, out = start, []
        while d <= end:
            out += [f"{d.isoformat()}T{h:02d}:00" for h in range(24)]
            d += timedelta(days=1)
        return out

    def fake(url, secret=None, tries=4):
        calls.append(url)
        if "firms" in url:
            return sample_fires_csv
        qs = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        n_loc = len(qs["latitude"].split("%2C"))
        times = hourly(datetime.strptime(qs["start_date"], "%Y-%m-%d").date(),
                       datetime.strptime(qs["end_date"], "%Y-%m-%d").date())
        if "archive-api" in url and "boundary_layer_height" in url:
            loc = {"hourly": {"time": times, "boundary_layer_height": [300.0 + 40 * (i % 24) for i in range(len(times))],
                              "wind_speed_10m": [1.0 + (i % 5) for i in range(len(times))]}}
        elif "archive-api" in url:
            loc = {"hourly": {"time": times, "wind_speed_10m": [15.0] * len(times), "wind_direction_10m": [315.0] * len(times)}}
        else:
            loc = {"hourly": {"time": times, "pm2_5": [90.0 + (i % 24) for i in range(len(times))]}}
        return json.dumps([loc] * n_loc)
    return fake


def test_api_mode_end_to_end_with_faked_network(monkeypatch, tmp_path, sample_fires_csv):
    calls = []
    monkeypatch.setattr(bt, "http_get", _fake_http(sample_fires_csv, calls))
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    args = bt.parse_args(["--start", "2025-11-01", "--end", "2025-11-06", "--firms-key", "SECRET",
                          "--cache-dir", str(tmp_path / "cache")])
    rep = bt.run(args)
    assert rep["n_rows"] == 6 * len(CITIES)
    assert "CAMS" in rep["truth"] and any("CAMS" in n for n in rep["notes"])
    assert any("ERA5" in n for n in rep["notes"])
    n_calls = len(calls)
    assert any("firms" in u for u in calls) and any("archive-api" in u for u in calls) and any("air-quality" in u for u in calls)

    bt.run(args)                                   # second run must be served entirely from the on-disk cache
    assert len(calls) == n_calls


def test_api_mode_fetches_and_uses_meteorology(monkeypatch, tmp_path, sample_fires_csv):
    calls = []
    monkeypatch.setattr(bt, "http_get", _fake_http(sample_fires_csv, calls))
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    rep = bt.run(bt.parse_args(["--start", "2025-11-01", "--end", "2025-11-08", "--firms-key", "K", "--cache-dir", str(tmp_path)]))
    assert any("boundary_layer_height" in u for u in calls)
    assert rep["n_met_rows"] == rep["n_rows"] > 0
    assert any(r["inv_vi"] is not None and r["smoke_index"] is not None for r in rep["_rows"])
    calls.clear()
    rep2 = bt.run(bt.parse_args(["--start", "2025-11-01", "--end", "2025-11-08", "--firms-key", "K", "--no-met",
                                 "--cache-dir", str(tmp_path)]))
    assert rep2["n_met_rows"] == 0 and not any("boundary_layer_height" in u for u in calls)


def test_ventilation_stats_basics():
    s = model.ventilation_stats([1000.0] * 30, [2.0] * 30)
    assert s["vi_mean"] == 2000.0 and s["vi_min"] == 2000.0 and s["inv_vi"] == pytest.approx(1 / 2000)
    mixed = model.ventilation_stats([1000.0] * 15 + [100.0] * 15, [2.0] * 15 + [1.0] * 15)   # day 2000, stagnant night 100
    assert mixed["inv_vi"] > 1 / mixed["vi_mean"] * 2        # exposure is dominated by the stagnant hours, not the mean
    assert model.ventilation_stats([1000.0] * 10, [2.0] * 10) is None                          # too few hours
    assert model.ventilation_stats([None] * 30, [2.0] * 30) is None
    floored = model.ventilation_stats([10.0] * 30, [0.1] * 30)                                  # VI=1, floored at 100
    assert floored["inv_vi"] == pytest.approx(1 / model.VI_FLOOR)
    assert model.smoke_index(100.0, None) is None
    assert model.smoke_index(100.0, s) == pytest.approx(100.0 * (1 / 2000) * model.SMOKE_INDEX_SCALE, abs=0.01)


def test_ventilation_does_not_change_risk_level_yet():
    delhi = CITIES["delhi"]
    lat, lon = advance(delhi["lat"], delhi["lon"], 315.0, 150.0)
    cell = model.FireCell(lat, lon, 400.0, 10)
    wind = sources.synthetic_wind(315.0, 15.0)
    plain = model.assess_city(delhi, [cell], wind)
    vent = model.ventilation_stats([200.0] * 48, [0.5] * 48)       # extremely stagnant
    withv = model.assess_city(delhi, [cell], wind, ventilation=vent)
    assert withv["risk_level"] == plain["risk_level"] and withv["smoke_load"] == plain["smoke_load"]
    assert plain["smoke_index"] is None and withv["smoke_index"] > 0 and withv["ventilation"]["vi_mean"] == 100.0


def test_met_archive_windows_and_parse_ventilation():
    times = [f"2025-11-0{d}T{h:02d}:00" for d in (3, 4) for h in range(24)]
    one = {"hourly": {"time": times, "boundary_layer_height": [500.0] * 48, "wind_speed_10m": [2.0] * 48}}
    arch = bt.MetArchive()
    arch.add([one, one], ["delhi", "jaipur"])
    issue = datetime(2025, 11, 3, tzinfo=UTC)
    assert arch.ventilation("delhi", issue)["vi_mean"] == 1000.0
    assert arch.ventilation("delhi", issue + timedelta(hours=40)) is None             # window runs off the end of the data
    assert arch.ventilation("atlantis", issue) is None
    got = sources.parse_ventilation([one, one], {"delhi": CITIES["delhi"], "jaipur": CITIES["jaipur"]}, issue)
    assert set(got) == {"delhi", "jaipur"} and got["jaipur"]["vi_mean"] == 1000.0


def test_api_mode_needs_a_firms_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    args = bt.parse_args(["--start", "2025-11-01", "--end", "2025-11-02", "--firms-key", "", "--cache-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="FIRMS"):
        bt.run(args)


def test_http_get_never_leaks_the_key(monkeypatch):
    import urllib.error

    def boom(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
    monkeypatch.setattr(bt.sources, "_get", boom)
    with pytest.raises(RuntimeError) as exc:
        bt.http_get("https://firms.example/api/area/csv/TOPSECRET/x", secret="TOPSECRET")
    assert "TOPSECRET" not in str(exc.value) and exc.value.__cause__ is None and exc.value.__suppress_context__


FIRES_HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"


def _snapshot(root, y, m, d_, hhmm, fires_text, with_wind=True):
    folder = root / "raw" / f"{y:04d}" / f"{m:02d}" / f"{d_:02d}" / hhmm
    folder.mkdir(parents=True)
    (folder / "fires.csv").write_text(fires_text)
    if with_wind:
        times = [f"{y:04d}-{m:02d}-{d_:02d}T{h:02d}:00" for h in range(24)] + [f"{y:04d}-{m:02d}-{d_ + 1:02d}T{h:02d}:00" for h in range(24)]
        one = {"hourly": {"time": times, "wind_speed_10m": [15.0] * 48, "wind_direction_10m": [315.0] * 48}}
        (folder / "wind.json").write_text(json.dumps([one] * 30))
    return folder


def test_snapshots_mode(tmp_path, sample_fires_csv):
    # the sample fires were detected 2026-10-08 08:12 UTC, so snapshots issued that evening see them inside the 24 h window
    d = _snapshot(tmp_path, 2026, 10, 8, "2000", sample_fires_csv)
    _snapshot(tmp_path, 2026, 10, 8, "2100", sample_fires_csv)       # a 21:00 snapshot must be skipped at --snapshot-hour 20
    cases = bt.cases_from_snapshots(tmp_path, 20)
    assert len(cases) == 1 and cases[0].issue == datetime(2026, 10, 8, 20, tzinfo=UTC) and len(cases[0].fires) == 17
    assert cases[0].vent == {}                                      # no met.json in this snapshot: ventilation simply absent
    assert len(bt.cases_from_snapshots(tmp_path, None)) == 2

    times = [f"2026-10-08T{h:02d}:00" for h in range(24)] + [f"2026-10-09T{h:02d}:00" for h in range(24)]
    met = {"hourly": {"time": times, "boundary_layer_height": [500.0] * 48, "wind_speed_10m": [2.0] * 48}}
    (d / "met.json").write_text(json.dumps([met] * len(CITIES)))
    with_met = bt.cases_from_snapshots(tmp_path, 20)[0]
    assert set(with_met.vent) == set(CITIES) and with_met.vent["delhi"]["vi_mean"] == 1000.0


def test_snapshots_apply_the_24_hour_window_and_skip_empty_ones(tmp_path, sample_fires_csv, capsys):
    _snapshot(tmp_path, 2026, 10, 8, "2000", sample_fires_csv)                       # fires are ~12 h old: kept
    _snapshot(tmp_path, 2026, 10, 10, "0300", sample_fires_csv)                      # same file, but now 43 h old: dropped -> empty
    _snapshot(tmp_path, 2026, 10, 9, "0100", FIRES_HEADER)                           # the pre-fix bug: a header and no rows
    cases = bt.cases_from_snapshots(tmp_path, None)
    assert [c.issue for c in cases] == [datetime(2026, 10, 8, 20, tzinfo=UTC)]
    assert "skipped 2 snapshot(s) with zero fire detections" in capsys.readouterr().err
    kept = bt.cases_from_snapshots(tmp_path, None, keep_empty=True)
    assert len(kept) == 3 and sorted(len(c.fires) for c in kept) == [0, 0, 17]


def test_parse_args_requires_a_data_mode():
    with pytest.raises(SystemExit):
        bt.parse_args([])
    with pytest.raises(SystemExit):
        bt.parse_args(["--demo", "--thresholds", "1,2"])
