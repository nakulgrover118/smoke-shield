"""Back-test the smoke-arrival model against observed PM2.5, and tune its CALIBRATE constants.

For every issue day the model sees only what the live system would see (fires from the previous
24 h + the wind forecast from the issue time) and predicts a smoke load per city. We then ask:
did PM2.5 in the next 48 h actually go up when the model said it would?

Three yardsticks, so the result is not just "it correlates":
  * model smoke_load   - fires + wind (the thing we built)
  * fires only         - total fire radiative power, no wind. If the model cannot beat this, the wind adds nothing.
  * persistence        - mean PM2.5 over the previous 24 h. The "just look at today's AQI" baseline.

Data modes (fires + wind -> predictions, then PM2.5 truth):
  --demo                         synthetic season, no keys or network. HARNESS CHECK ONLY: numbers are meaningless.
  --start/--end  (+ FIRMS key)   FIRMS fires + Open-Meteo wind reanalysis for a past season.
  --snapshots DIR                the hourly raw/ snapshots the ingest Lambda wrote to S3 (aws s3 sync s3://<bucket>/raw DIR/raw).
                                 This uses *archived real forecasts*, so it measures real forecast skill.
Truth:
  --truth-csv FILE               columns: city,timestamp,pm25 (e.g. CPCB / OpenAQ export). Best option.
  (default) CAMS via Open-Meteo  a model, not measurements, and it reads low over India. Fine for a first pass only.

Examples:
  python scripts/backtest.py --demo
  python scripts/backtest.py --start 2025-10-20 --end 2025-11-25 --truth-csv data/pm25.csv --tune
  python scripts/backtest.py --snapshots data/raw --snapshot-hour 0 --truth-csv data/pm25.csv --out report.json
"""
import argparse
import bisect
import csv
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))

from common import filters, model, sources  # noqa: E402
from common.cities import CITIES, FIRE_BBOX, grid_points  # noqa: E402
from common.model import LEVELS, LOAD_THRESHOLDS, ModelParams, assess_city, cluster_fires, compute_paths  # noqa: E402

UTC = timezone.utc
HORIZON = timedelta(hours=48)
FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/1/{date}"
# ERA5 reanalysis = what the wind actually did. (Open-Meteo's "historical-forecast" endpoint returned
# bit-identical values for Nov 2025, so it is not a source of archived forecasts. For real forecast skill use --snapshots.)
WIND_URL = "https://archive-api.open-meteo.com/v1/archive"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


# =============================================================================================
# Statistics (pure python so the script runs anywhere)
# =============================================================================================

def rankdata(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    a, b = rankdata(list(xs)), rankdata(list(ys))
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def partial_spearman(x, y, z):
    """Spearman correlation of x and y after removing what z explains in both (first-order partial correlation of ranks)."""
    rxy, rxz, ryz = spearman(x, y), spearman(x, z), spearman(y, z)
    if rxy is None or rxz is None or ryz is None:
        return None
    denom = math.sqrt((1 - rxz ** 2) * (1 - ryz ** 2))
    return None if denom == 0 else (rxy - rxz * ryz) / denom


def auc(scores, labels):
    """P(score of a random event day > score of a random non-event day); ties count half."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = rankdata(list(scores))
    rank_sum = sum(r for r, l in zip(ranks, labels) if l)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def prf(pred, truth):
    tp = sum(p and t for p, t in zip(pred, truth))
    fp = sum(p and not t for p, t in zip(pred, truth))
    fn = sum((not p) and t for p, t in zip(pred, truth))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def best_threshold(loads, labels):
    """Load cut-off that maximises F1 for 'event' labels. Returns (threshold, f1) or None."""
    if not any(labels):
        return None
    best = None
    for t in sorted({l for l in loads if l > 0}):
        f1 = prf([l >= t for l in loads], labels)["f1"]
        if best is None or f1 > best[1] + 1e-12:
            best = (t, f1)
    return best


def block_bootstrap_ci(xs, ys, stat, block=3, draws=400, seed=0):
    """95% CI that resamples 3-day blocks, because consecutive days are not independent."""
    n = len(xs)
    if n < 10:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        idx = []
        while len(idx) < n:
            s = rng.randrange(n)
            idx.extend(range(s, min(s + block, n)))
        idx = idx[:n]
        v = stat([xs[i] for i in idx], [ys[i] for i in idx])
        if v is not None:
            vals.append(v)
    if len(vals) < draws // 2:
        return None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[min(int(0.975 * len(vals)), len(vals) - 1)]


# =============================================================================================
# Data containers
# =============================================================================================

@dataclass
class Case:
    """One issue time: the fires, wind and (optionally) per-city ventilation the live system would have seen."""
    issue: datetime
    fires: list
    wind: object
    vent: dict = field(default_factory=dict)   # city key -> model.ventilation_stats(...) over the next 48 h
    cells: list = field(init=False)

    def __post_init__(self):
        self.cells = cluster_fires(self.fires)


class Truth:
    """Observed PM2.5 per city. Works for hourly or daily series."""

    def __init__(self, series):
        self._t, self._v, self._spacing = {}, {}, {}
        for city, pts in series.items():
            pts = sorted(pts)
            if not pts:
                continue
            self._t[city] = [p[0] for p in pts]
            self._v[city] = [p[1] for p in pts]
            diffs = [(b - a).total_seconds() / 3600 for a, b in zip(self._t[city], self._t[city][1:]) if b > a]
            self._spacing[city] = statistics.median(diffs) if diffs else 1.0

    def spacing(self, city):
        return self._spacing.get(city, 1.0)

    def window(self, city, start, end):
        """[(time, value)] in [start, end), or None if under half the expected observations are present."""
        t = self._t.get(city)
        if not t:
            return None
        i, j = bisect.bisect_left(t, start), bisect.bisect_left(t, end)
        pts = list(zip(t[i:j], self._v[city][i:j]))
        need = max(1, int(0.5 * (end - start).total_seconds() / 3600 / self._spacing[city]))
        return pts if len(pts) >= need else None


# =============================================================================================
# Loading truth
# =============================================================================================

TS_FORMATS = ("%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y/%m/%d %H:%M")


def parse_ts(text, utc_offset_h=0.0):
    s = text.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for f in TS_FORMATS:
            try:
                dt = datetime.strptime(s, f)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unrecognised timestamp {text!r}")
    if dt.tzinfo is None:   # naive = local clock time of the data source (CPCB exports are IST = +5.5)
        dt = (dt - timedelta(hours=utc_offset_h)).replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_truth_csv(path, utc_offset_h=0.0, cities=None):
    cities = cities or CITIES
    lookup = {}
    for key, c in cities.items():
        lookup[key] = key
        lookup[c["name"].lower()] = key
    series, skipped = {}, 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            raise SystemExit(f"{path}: need a column named one of {names}; found {list(cols)}")

        c_city, c_ts, c_pm = pick("city"), pick("timestamp", "datetime", "date", "time"), \
            pick("pm25", "pm2_5", "pm2.5", "pm_2_5", "value")
        for row in reader:
            key = lookup.get((row[c_city] or "").strip().lower())
            try:
                v = float(row[c_pm])
                if key is None or v < 0 or math.isnan(v):
                    raise ValueError
                series.setdefault(key, []).append((parse_ts(row[c_ts], utc_offset_h), v))
            except (ValueError, TypeError):
                skipped += 1
    if not series:
        raise SystemExit(f"{path}: no usable rows for cities {list(cities)}")
    if skipped:
        print(f"note: skipped {skipped} unusable truth rows", file=sys.stderr)
    return Truth(series)


# =============================================================================================
# Fetching (cached on disk so re-runs are instant and polite to the free APIs)
# =============================================================================================

def http_get(url, secret=None, tries=4):
    shown = url.replace(secret, "***") if secret else url
    for attempt in range(tries):
        try:
            return sources._get(url)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} from {shown}") from None   # `from None`: keep the key out of tracebacks
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"network error ({e.reason}) from {shown}") from None


def cached_text(path, fetch):
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def fetch_firms_day(key, source, day, cache):
    bbox = ",".join(str(x) for x in FIRE_BBOX)
    url = FIRMS_AREA.format(key=key, source=source, bbox=bbox, date=day.isoformat())

    def fetch():
        text = http_get(url, key)
        if not text.lstrip().startswith("latitude"):
            raise RuntimeError(f"FIRMS returned an unexpected body for {day}: {text[:100]!r}")
        time.sleep(0.3)
        return text
    return cached_text(cache / f"firms_{source}_{day}.csv", fetch)


class WindArchive:
    """Hourly wind per grid point over a long period; slices a 72 h forecast-like field for any issue time."""

    def __init__(self):
        self.series = {}

    def add(self, payload, points):
        for pt, loc in zip(points, sources._as_list(payload)):
            h = loc["hourly"]
            d = self.series.setdefault(pt, {})
            for t, s, w in zip(h["time"], h["wind_speed_10m"], h["wind_direction_10m"]):
                if s is not None and w is not None:
                    d[datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)] = (s, w)

    def field_at(self, issue, hours=72):
        pts = {}
        for pt, d in self.series.items():
            seq = []
            for i in range(hours):
                v = d.get(issue + timedelta(hours=i))
                if v is None:
                    break
                seq.append(v)
            if seq:
                pts[pt] = seq
        return model.WindField(pts) if pts else None


def fetch_wind_archive(first_day, last_day, cache):
    points = grid_points()
    lats, lons = sources._multi(points)
    arch = WindArchive()
    day = first_day
    while day <= last_day:
        end = min(day + timedelta(days=6), last_day)
        qs = urllib.parse.urlencode({
            "latitude": lats, "longitude": lons, "start_date": day.isoformat(), "end_date": end.isoformat(),
            "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "kmh", "timezone": "UTC"})
        url = f"{WIND_URL}?{qs}"

        def fetch(url=url):
            text = http_get(url)
            time.sleep(1.0)
            return text
        arch.add(json.loads(cached_text(cache / f"wind_era5_{day}_{end}.json", fetch)), points)
        day = end + timedelta(days=1)
    return arch


class MetArchive:
    """Hourly boundary-layer height + 10 m wind (m/s) per city; yields the ventilation stats for any 48 h window."""

    def __init__(self):
        self.series = {}

    def add(self, payload, keys):
        for key, loc in zip(keys, sources._as_list(payload)):
            h = loc["hourly"]
            d = self.series.setdefault(key, {})
            for t, b, w in zip(h["time"], h["boundary_layer_height"], h["wind_speed_10m"]):
                if b is not None and w is not None:
                    d[datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)] = (b, w)

    def ventilation(self, city, issue, hours=48):
        d = self.series.get(city, {})
        vals = [d.get(issue + timedelta(hours=i)) for i in range(hours)]
        return model.ventilation_stats([v[0] if v else None for v in vals], [v[1] if v else None for v in vals])


def fetch_met_archive(cities, first_day, last_day, cache):
    keys = list(cities)
    lats, lons = sources._multi([(c["lat"], c["lon"]) for c in cities.values()])
    arch = MetArchive()
    day = first_day
    while day <= last_day:
        end = min(day + timedelta(days=29), last_day)
        qs = urllib.parse.urlencode({
            "latitude": lats, "longitude": lons, "start_date": day.isoformat(), "end_date": end.isoformat(),
            "hourly": "boundary_layer_height,wind_speed_10m", "wind_speed_unit": "ms", "timezone": "UTC"})
        url = f"{WIND_URL}?{qs}"

        def fetch(url=url):
            text = http_get(url)
            time.sleep(1.0)
            return text
        arch.add(json.loads(cached_text(cache / f"met_era5_{day}_{end}.json", fetch)), keys)
        day = end + timedelta(days=1)
    return arch


def fetch_truth_cams(cities, first_day, last_day, cache):
    keys = list(cities)
    lats, lons = sources._multi([(c["lat"], c["lon"]) for c in cities.values()])
    series = {k: [] for k in keys}
    day = first_day
    while day <= last_day:
        end = min(day + timedelta(days=29), last_day)
        qs = urllib.parse.urlencode({"latitude": lats, "longitude": lons, "start_date": day.isoformat(),
                                     "end_date": end.isoformat(), "hourly": "pm2_5", "timezone": "UTC"})
        url = f"{AQ_URL}?{qs}"

        def fetch(url=url):
            text = http_get(url)
            time.sleep(1.0)
            return text
        payload = json.loads(cached_text(cache / f"cams_{day}_{end}.json", fetch))
        for key, loc in zip(keys, sources._as_list(payload)):
            h = loc["hourly"]
            for t, v in zip(h["time"], h["pm2_5"]):
                if v is not None:
                    series[key].append((datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC), v))
        day = end + timedelta(days=1)
    return Truth(series)


# =============================================================================================
# Building cases
# =============================================================================================

def cases_from_api(start, end, firms_key, firms_source, cache, with_met=True):
    if not firms_key:
        raise SystemExit("Need a FIRMS key: --firms-key or the FIRMS_MAP_KEY env var "
                         "(free at https://firms.modaps.eosdis.nasa.gov/api/map_key/)")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    print(f"fetching ERA5 wind {days[0] + timedelta(days=1)} .. {days[-1] + timedelta(days=4)}", file=sys.stderr)
    arch = fetch_wind_archive(days[0] + timedelta(days=1), days[-1] + timedelta(days=4), cache)
    met = fetch_met_archive(CITIES, days[0] + timedelta(days=1), days[-1] + timedelta(days=4), cache) if with_met else None
    cases = []
    for d in days:
        print(f"  fires {d}", file=sys.stderr)
        fires = sources.parse_fires(fetch_firms_day(firms_key, firms_source, d, cache))
        # fires detected on day D, forecast issued at 00:00 UTC (05:30 IST) the next morning
        issue = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1)
        wind = arch.field_at(issue)
        if wind is None:
            print(f"  skipping {d}: no wind data", file=sys.stderr)
            continue
        vent = {k: v for k in CITIES if met and (v := met.ventilation(k, issue))}
        cases.append(Case(issue, fires, wind, vent))
    return cases


def cases_from_snapshots(root, hour, keep_empty=False):
    """Cases from the ingest Lambda's raw/YYYY/MM/DD/HHMM snapshots.

    Fires are cut to the 24 h before each snapshot's issue time, exactly as the live ingest does. Snapshots with zero detections
    are skipped unless keep_empty: in the burning season that means a feed outage or the pre-fix day_range bug (runs between
    00:00 and ~10:00 UTC saw nothing), not a genuinely fire-free day, and scoring them would teach the model that silence is real.
    """
    cases, skipped_empty = [], 0
    for fires_path in sorted(Path(root).glob("**/fires.csv")):
        d = fires_path.parent
        parts = d.parts[-4:]   # YYYY / MM / DD / HHMM, as written by the ingest Lambda
        try:
            issue = datetime(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3][:2]), int(parts[3][2:4]), tzinfo=UTC)
            if hour is not None and issue.hour != hour:
                continue
            wind = sources.parse_wind(json.loads((d / "wind.json").read_text(encoding="utf-8")), issue)
        except (ValueError, IndexError, OSError, KeyError):
            continue
        vent = {}
        if (d / "met.json").exists():   # written by the ingest Lambda since the ventilation term was added
            try:
                vent = sources.parse_ventilation(json.loads((d / "met.json").read_text(encoding="utf-8")), CITIES, issue)
            except (ValueError, KeyError):
                vent = {}
        fires = sources.parse_fires(fires_path.read_text(encoding="utf-8"), issue)
        if not fires and not keep_empty:
            skipped_empty += 1
            continue
        cases.append(Case(issue, fires, wind, vent))
    if skipped_empty:
        print(f"note: skipped {skipped_empty} snapshot(s) with zero fire detections in the 24 h window (use --keep-empty-snapshots to include them)",
              file=sys.stderr)
    return cases


def demo_data(days=45, seed=7):
    """Synthetic season where PM2.5 responds to the model's own prediction. Proves the harness runs; proves nothing else."""
    rng = random.Random(seed)
    first = datetime(2025, 10, 20, tzinfo=UTC)
    cases = []
    for d in range(days):
        n = int(30 + 450 * rng.uniform(0.2, 1.0))
        fires = [{"lat": rng.uniform(29.8, 31.6), "lon": rng.uniform(74.0, 76.8), "frp": rng.uniform(3, 40)} for _ in range(n)]
        cases.append(Case(first + timedelta(days=d), fires, sources.synthetic_wind(rng.uniform(270, 360), rng.uniform(6, 24))))
    t0 = first - timedelta(days=2)
    n_days = days + 5
    hours = n_days * 24
    # Weather: a per-day, per-city stagnation factor g (>1 = stagnant). PM2.5 is multiplied by g; ventilation is 1500 / g.
    g = {k: [math.exp(rng.gauss(0, 0.25)) for _ in range(n_days)] for k in CITIES}
    base = {k: (110 if k == "delhi" else 80) for k in CITIES}
    vals = {k: [max(5.0, rng.gauss(base[k], 15)) for _ in range(hours)] for k in CITIES}
    for case in cases:
        for k, rec in predict([case], CITIES, model.DEFAULT_PARAMS, LOAD_THRESHOLDS)[0].items():
            if rec["arrival_hour"] is None:
                continue
            off = int((case.issue - t0).total_seconds() / 3600)
            for i in range(off + rec["window_start_hour"], min(off + rec["window_end_hour"] + 6, hours)):
                vals[k][i] += min(0.1 * rec["smoke_load"], 350)
    for k in CITIES:
        vals[k] = [v * g[k][i // 24] for i, v in enumerate(vals[k])]
    for case in cases:
        d0 = int((case.issue - t0).days)
        case.vent = {}
        for k in CITIES:
            mean_g = (g[k][d0] + g[k][d0 + 1]) / 2
            vi = 1500.0 / mean_g
            case.vent[k] = {"vi_mean": round(vi, 1), "vi_min": round(vi * 0.5, 1), "inv_vi": 1.0 / vi}
    truth = Truth({k: [(t0 + timedelta(hours=i), v) for i, v in enumerate(vs)] for k, vs in vals.items()})
    return cases, truth


# =============================================================================================
# Prediction + evaluation
# =============================================================================================

def predict(cases, cities, params, thresholds, paths_per_case=None):
    out = []
    for i, case in enumerate(cases):
        paths = paths_per_case[i] if paths_per_case else compute_paths(case.cells, case.wind, params)
        out.append({k: assess_city(c, case.cells, case.wind, params=params, paths=paths, thresholds=thresholds,
                                   ventilation=case.vent.get(k))
                    for k, c in cities.items()})
    return out


def build_rows(cases, preds, truth, cities):
    rows = []
    for case, recs in zip(cases, preds):
        frp_total = sum(c.frp for c in case.cells)
        for key in cities:
            nxt = truth.window(key, case.issue, case.issue + HORIZON)
            if nxt is None:
                continue
            prev = truth.window(key, case.issue - timedelta(hours=24), case.issue)
            peak_h = None
            if truth.spacing(key) <= 3:
                peak_h = (max(nxt, key=lambda p: p[1])[0] - case.issue).total_seconds() / 3600
            rec = recs[key]
            rows.append({
                "issue": case.issue, "city": key, "level": rec["risk_level"], "load": rec["smoke_load"],
                "arrival_hour": rec["arrival_hour"], "peak_hour": rec["peak_hour"], "frp_total": frp_total,
                "persistence": statistics.fmean(v for _, v in prev) if prev else None,
                "obs": statistics.fmean(v for _, v in nxt), "obs_peak_hour": peak_h,
                "inv_vi": (rec["ventilation"] or {}).get("inv_vi"), "vi_mean": (rec["ventilation"] or {}).get("vi_mean"),
                "smoke_index": rec["smoke_index"]})
    return rows


def _by_city(rows):
    out = {}
    for r in rows:
        out.setdefault(r["city"], []).append(r)
    return {c: sorted(rs, key=lambda r: r["issue"]) for c, rs in sorted(out.items())}


def mean_city_rho(rows, min_n=8, objective="change"):
    """Tuning objective, averaged over cities.
    change : Spearman of load vs the CHANGE in PM2.5 over the previous 24 h. Raw obs would reward fitting the
             season-long trend (fires fall while winter PM2.5 rises).
    partial: Spearman of load vs PM2.5 after removing what ventilation explains (needs meteorology in the rows)."""
    rhos = []
    for rs in _by_city(rows).values():
        if objective == "partial":
            rs = [r for r in rs if r["inv_vi"] is not None]
            rho = partial_spearman([r["load"] for r in rs], [r["obs"] for r in rs], [r["inv_vi"] for r in rs]) \
                if len(rs) >= min_n else None
        else:
            rs = [r for r in rs if r["persistence"] is not None]
            rho = spearman([r["load"] for r in rs], [r["obs"] - r["persistence"] for r in rs]) if len(rs) >= min_n else None
        if rho is not None:
            rhos.append(rho)
    return statistics.fmean(rhos) if rhos else None


def summarize(rows, event_pm25, pm_levels):
    cities = {}
    for city, rs in _by_city(rows).items():
        load, obs, frp = [r["load"] for r in rs], [r["obs"] for r in rs], [r["frp_total"] for r in rs]
        labels = [o >= event_pm25 for o in obs]
        pr = [r for r in rs if r["persistence"] is not None]
        pers, pobs = [r["persistence"] for r in pr], [r["obs"] for r in pr]
        # Does load predict the CHANGE in PM2.5 vs the previous 24 h? Strips out season-long trends and autocorrelation.
        dload, dobs = [r["load"] for r in pr], [r["obs"] - r["persistence"] for r in pr]
        # Weather: does smoke carry information beyond ventilation (boundary-layer height x wind)?
        vr = [r for r in rs if r["inv_vi"] is not None]
        vload, vobs, inv = [r["load"] for r in vr], [r["obs"] for r in vr], [r["inv_vi"] for r in vr]
        sidx = [r["smoke_index"] for r in vr]
        vlabels = [o >= event_pm25 for o in vobs]
        vp = [r for r in vr if r["persistence"] is not None]
        vdelta = [r["obs"] - r["persistence"] for r in vp]
        packed = list(zip(vload, inv))
        weather = {
            "n_met": len(vr),
            "rho_vent": spearman(inv, vobs), "rho_index": spearman(sidx, vobs),
            "rho_partial": partial_spearman(vload, vobs, inv),
            "rho_partial_ci": block_bootstrap_ci(packed, vobs, lambda a, b: partial_spearman([p[0] for p in a], b, [p[1] for p in a])),
            "rho_vent_delta": spearman([r["inv_vi"] for r in vp], vdelta),
            "rho_index_delta": spearman([r["smoke_index"] for r in vp], vdelta),
            "auc_vent": auc(inv, vlabels), "auc_index": auc(sidx, vlabels)}
        cities[city] = {
            **weather,
            "n": len(rs), "event_rate": sum(labels) / len(labels),
            "rho": spearman(load, obs), "rho_ci": block_bootstrap_ci(load, obs, spearman),
            "rho_delta": spearman(dload, dobs), "rho_delta_ci": block_bootstrap_ci(dload, dobs, spearman),
            "rho_frp": spearman(frp, obs), "rho_persist": spearman(pers, pobs),
            "auc": auc(load, labels), "auc_frp": auc(frp, labels),
            "auc_persist": auc(pers, [o >= event_pm25 for o in pobs]) if pr else None}

    def mean_of(k):
        v = [c[k] for c in cities.values() if c[k] is not None]
        return statistics.fmean(v) if v else None

    labels = [r["obs"] >= event_pm25 for r in rows]
    by_level = {}
    for lv in LEVELS:
        obs = [r["obs"] for r in rows if r["level"] == lv]
        by_level[lv] = {"n": len(obs), "mean_obs": statistics.fmean(obs) if obs else None,
                        "median_obs": statistics.median(obs) if obs else None,
                        "event_rate": sum(o >= event_pm25 for o in obs) / len(obs) if obs else None}
    detection = {lv: prf([LEVELS.index(r["level"]) >= LEVELS.index(lv) for r in rows], labels)
                 for lv in ("MODERATE", "HIGH")}

    errs = [abs(r["peak_hour"] - r["obs_peak_hour"]) for r in rows
            if LEVELS.index(r["level"]) >= 1 and r["obs"] >= event_pm25
            and r["peak_hour"] is not None and r["obs_peak_hour"] is not None]
    timing = {"n": len(errs), "median_abs_err_h": statistics.median(errs) if errs else None,
              "p75_abs_err_h": sorted(errs)[int(0.75 * (len(errs) - 1))] if errs else None}

    loads = [r["load"] for r in rows]
    suggested, prev = [], 0.0
    for lvl in pm_levels:
        lab = [r["obs"] >= lvl for r in rows]
        bt = best_threshold(loads, lab)
        p = sum(lab) / len(lab)
        always_f1 = 2 * p / (1 + p)   # F1 of simply alerting every day; a cut-off must beat this to mean anything
        # ...and within each city the load must rank event days above non-event days. Pooled AUC is fooled when cities
        # differ in both baseline PM2.5 and typical load (Simpson's paradox), so judge it city by city.
        city_aucs = [a for a in (auc([r["load"] for r in rs], [r["obs"] >= lvl for r in rs]) for rs in _by_city(rows).values())
                     if a is not None]
        rank_ok = bool(city_aucs) and statistics.fmean(city_aucs) >= 0.6
        if bt is None or bt[1] <= always_f1 + 0.03 or not rank_ok:
            suggested.append(None)
        else:
            prev = max(prev, bt[0])
            suggested.append(round(prev, 1))

    return {"n_rows": len(rows), "event_pm25": event_pm25, "cities": cities,
            "mean_rho": mean_of("rho"), "mean_rho_delta": mean_of("rho_delta"),
            "mean_rho_vent": mean_of("rho_vent"), "mean_rho_index": mean_of("rho_index"),
            "mean_rho_partial": mean_of("rho_partial"), "mean_rho_vent_delta": mean_of("rho_vent_delta"),
            "mean_rho_index_delta": mean_of("rho_index_delta"),
            "mean_auc_vent": mean_of("auc_vent"), "mean_auc_index": mean_of("auc_index"),
            "n_met_rows": sum(c["n_met"] for c in cities.values()),
            "mean_rho_frp": mean_of("rho_frp"), "mean_rho_persist": mean_of("rho_persist"),
            "mean_auc": mean_of("auc"), "mean_auc_frp": mean_of("auc_frp"), "mean_auc_persist": mean_of("auc_persist"),
            "by_level": by_level, "detection": detection, "timing": timing,
            "pm_levels": list(pm_levels), "suggested_thresholds": suggested}


def filter_cases(cases, mode):
    """Apply the crop-fire filter to every case. -> (new cases, summed filter stats). Originals keep their raw fires."""
    out, tot = [], {"raw": 0, "kept": 0, "urban": 0, "static": 0}
    for c in cases:
        kept, st = filters.filter_fires(c.fires, mode)
        for k in tot:
            tot[k] += st[k]
        out.append(Case(c.issue, kept, c.wind, c.vent))
    return out, tot


def compare_filters(eval_raw, truth, cities, params, thresholds, event_pm25, pm_levels):
    """Same days, same params, different fire filters: does removing non-crop fires help?"""
    have_mask = filters.load_static_mask() is not None
    out = []
    for mode in filters.MODES:
        if mode in ("static", "all") and not have_mask:
            continue
        cs, st = filter_cases(eval_raw, mode)
        rows = build_rows(cs, predict(cs, cities, params, thresholds), truth, cities)
        if not rows:
            continue
        s = summarize(rows, event_pm25, pm_levels)
        out.append({"mode": mode, "kept_frac": st["kept"] / st["raw"] if st["raw"] else None,
                    "mean_rho": s["mean_rho"], "mean_rho_delta": s["mean_rho_delta"], "mean_auc": s["mean_auc"],
                    "moderate_plus_days": sum(s["by_level"][lv]["n"] for lv in LEVELS[1:])})
    return out


def tune(cases, truth, cities, thresholds, scales, radii, decays, min_n=8, objective="change"):
    results = []
    for s in scales:
        paths = [compute_paths(c.cells, c.wind, ModelParams(wind_scale=s)) for c in cases]   # depends on wind_scale only
        for r in radii:
            for d in decays:
                p = ModelParams(radius_km=r, decay_h=d, wind_scale=s)
                rows = build_rows(cases, predict(cases, cities, p, thresholds, paths), truth, cities)
                results.append((mean_city_rho(rows, min_n, objective), p))
        print(f"  tuned wind_scale={s}", file=sys.stderr)
    results.sort(key=lambda x: (x[0] is None, -(x[0] or 0.0)))
    return results


# =============================================================================================
# CLI
# =============================================================================================

def _day(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _floats(s):
    return [float(x) for x in s.split(",")]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("fires + wind")
    src.add_argument("--demo", action="store_true", help="synthetic season; harness check only")
    src.add_argument("--start", type=_day, help="first fire day (YYYY-MM-DD)")
    src.add_argument("--end", type=_day, help="last fire day (YYYY-MM-DD)")
    src.add_argument("--snapshots", help="folder containing the ingest Lambda's raw/YYYY/MM/DD/HHMM/ snapshots")
    src.add_argument("--snapshot-hour", type=int, default=0, help="use only snapshots issued at this UTC hour (default 0; -1 = all)")
    src.add_argument("--keep-empty-snapshots", action="store_true", help="also score snapshots with zero fire detections (skipped by default)")
    src.add_argument("--firms-key", default=os.environ.get("FIRMS_MAP_KEY"))
    src.add_argument("--firms-source", default="VIIRS_SNPP_SP",
                     help="VIIRS_SNPP_SP = archive (older than ~3 months); VIIRS_SNPP_NRT = recent")
    tr = ap.add_argument_group("truth")
    tr.add_argument("--truth-csv", help="city,timestamp,pm25 observations")
    tr.add_argument("--truth-utc-offset", type=float, default=0.0, help="hours ahead of UTC for naive CSV timestamps (IST = 5.5)")
    ev = ap.add_argument_group("evaluation")
    ev.add_argument("--cities", help="comma-separated subset, e.g. delhi,ludhiana")
    ev.add_argument("--event-pm25", type=float, default=150.0, help="observed 'event' = next-48h mean PM2.5 at or above this (ug/m3)")
    ev.add_argument("--pm-levels", type=_floats, default=[100.0, 150.0, 250.0],
                    help="PM2.5 cut-offs that define MODERATE/HIGH/SEVERE for threshold suggestions")
    ev.add_argument("--thresholds", type=_floats, help="evaluate with these LOAD_THRESHOLDS instead of the model defaults (3 numbers)")
    ev.add_argument("--radius", type=float, default=model.ARRIVAL_RADIUS_KM)
    ev.add_argument("--decay", type=float, default=model.DECAY_H)
    ev.add_argument("--wind-scale", type=float, default=model.WIND_SCALE)
    ev.add_argument("--tune", action="store_true", help="grid-search radius/decay/wind-scale on the first 60%% of days, report on the rest")
    ev.add_argument("--objective", choices=("change", "partial"), default="change",
                    help="what --tune optimises: load vs change in PM2.5, or load vs PM2.5 after controlling for ventilation")
    ev.add_argument("--no-met", action="store_true", help="skip the ventilation (boundary-layer height) data")
    ev.add_argument("--filter", choices=filters.MODES, default=None,
                    help="crop-fire filter: none | urban | static | all (default: all, or none for --demo)")
    ev.add_argument("--compare-filters", action="store_true", help="also score every filter mode on the same days and params")
    out = ap.add_argument_group("output")
    out.add_argument("--cache-dir", default=str(ROOT / ".cache" / "backtest"))
    out.add_argument("--out", help="write the full report as JSON")
    out.add_argument("--csv", help="write one row per city-day (for plotting)")
    args = ap.parse_args(argv)
    if not (args.demo or args.snapshots or (args.start and args.end)):
        ap.error("choose a data mode: --demo, --snapshots DIR, or --start/--end")
    if args.thresholds is not None and len(args.thresholds) != 3:
        ap.error("--thresholds needs exactly 3 numbers")
    return args


def run(args):
    cities = {k: CITIES[k] for k in args.cities.split(",")} if args.cities else dict(CITIES)
    cache = Path(args.cache_dir)
    notes = []

    if args.demo:
        cases, truth = demo_data()
        data_label, truth_label = "SYNTHETIC DEMO - harness check only, numbers mean nothing", "synthetic"
    else:
        if args.snapshots:
            cases = cases_from_snapshots(args.snapshots, None if args.snapshot_hour < 0 else args.snapshot_hour, args.keep_empty_snapshots)
            data_label = f"S3 snapshots in {args.snapshots} (archived real forecasts)"
        else:
            cases = cases_from_api(args.start, args.end, args.firms_key, args.firms_source, cache, with_met=not args.no_met)
            data_label = f"FIRMS {args.firms_source} + Open-Meteo ERA5 wind"
            notes.append("Wind is ERA5 reanalysis (what actually happened), so skill here is an upper bound on live forecast skill. "
                         "Collect --snapshots for the real thing.")
        if not cases:
            raise SystemExit("no usable cases (no fires/wind found)")
        first_day = min(c.issue for c in cases).date() - timedelta(days=1)
        last_day = max(c.issue for c in cases).date() + timedelta(days=3)
        if args.truth_csv:
            truth = load_truth_csv(args.truth_csv, args.truth_utc_offset, cities)
            truth_label = f"CSV {args.truth_csv}"
        else:
            print(f"fetching CAMS PM2.5 {first_day} .. {last_day}", file=sys.stderr)
            truth = fetch_truth_cams(cities, first_day, last_day, cache)
            truth_label = "CAMS model via Open-Meteo"
            notes.append("Truth is CAMS model output, not measurements, and it reads low over India. Use --truth-csv for real numbers.")

    cases.sort(key=lambda c: c.issue)
    thresholds = tuple(args.thresholds) if args.thresholds else LOAD_THRESHOLDS
    params = ModelParams(args.radius, args.decay, args.wind_scale)
    mode = args.filter or ("none" if args.demo else "all")
    if mode in ("static", "all") and filters.load_static_mask() is None:
        notes.append("No static-source mask built (scripts/build_static_mask.py): only urban cores are filtered.")
    tuning = None
    train_raw, eval_raw = cases, cases
    if args.tune:
        if len(cases) >= 20:
            cut = int(len(cases) * 0.6)
            train_raw, eval_raw = cases[:cut], cases[cut:]
            notes.append(f"Tuned on {len(train_raw)} days ({train_raw[0].issue.date()}..{train_raw[-1].issue.date()}); "
                         f"results below are out-of-sample on {len(eval_raw)} days.")
        else:
            notes.append("Fewer than 20 days: tuned and evaluated on the same data, so results are optimistic.")
        train, _ = filter_cases(train_raw, mode)
        ranked = tune(train, truth, cities, thresholds, scales=[0.75, 1.0, 1.5, 2.0], radii=[40.0, 60.0, 100.0],
                      decays=[12.0, 24.0, 48.0], objective=args.objective)
        tuning = [{"mean_rho": s, **vars(p)} for s, p in ranked[:8]]
        if ranked[0][0] is not None:
            params = ranked[0][1]
    eval_cases, fstats = filter_cases(eval_raw, mode)
    if len(eval_cases) < 20:
        notes.append(f"Only {len(eval_cases)} issue days: treat every number as anecdotal.")

    preds = predict(eval_cases, cities, params, thresholds)
    rows = build_rows(eval_cases, preds, truth, cities)
    if not rows:
        raise SystemExit("no overlap between cases and observations - check dates, city names and --truth-utc-offset")
    report = summarize(rows, args.event_pm25, args.pm_levels)
    report.update({"data": data_label, "truth": truth_label, "notes": notes, "tuning": tuning,
                   "params": vars(params), "thresholds": list(thresholds), "filter": {"mode": mode, **fstats},
                   "filter_compare": compare_filters(eval_raw, truth, cities, params, thresholds, args.event_pm25, args.pm_levels)
                   if args.compare_filters else None,
                   "days": [eval_cases[0].issue.date().isoformat(), eval_cases[-1].issue.date().isoformat()]})
    report["_rows"] = rows
    return report


def _consistent(cities, key, floor=0.15, share=2 / 3):
    """True if at least `share` of cities have metric `key` >= floor: guards against one city dragging the mean over the line."""
    vals = [c[key] for c in cities.values()]
    return bool(vals) and sum((v or 0) >= floor for v in vals) / len(vals) >= share


def _f(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def print_report(rep):
    print(f"\nSmokeShield back-test\n  data : {rep['data']}\n  truth: {rep['truth']}\n  days : {rep['days'][0]} .. {rep['days'][1]}"
          f"   ({rep['n_rows']} city-days)")
    p = rep["params"]
    print(f"  model: radius {p['radius_km']:g} km, decay {p['decay_h']:g} h, wind x{p['wind_scale']:g}, "
          f"load thresholds {rep['thresholds']}")
    fl = rep["filter"]
    print(f"  fires: filter={fl['mode']}, kept {fl['kept']:,} of {fl['raw']:,} detections"
          f" (urban cores -{fl['urban']:,}, repeat-burn sites -{fl['static']:,})")
    for n in rep["notes"]:
        print(f"  ! {n}")

    print("\nHow well does predicted smoke_load rank the next-48h mean PM2.5?  (Spearman rho; 95% block-bootstrap CI)")
    print(f"  {'city':<11}{'n':>4}   {'model (fires+wind)':<26}{'fires only':>11}{'persistence':>13}{'model vs change*':>18}")
    for city, c in rep["cities"].items():
        ci = f"[{_f(c['rho_ci'][0])}, {_f(c['rho_ci'][1])}]" if c["rho_ci"] else ""
        print(f"  {city:<11}{c['n']:>4}   {_f(c['rho']):>5} {ci:<20}{_f(c['rho_frp']):>11}{_f(c['rho_persist']):>13}{_f(c['rho_delta']):>18}")
    print(f"  {'mean':<11}{'':>4}   {_f(rep['mean_rho']):>5} {'':<20}{_f(rep['mean_rho_frp']):>11}{_f(rep['mean_rho_persist']):>13}"
          f"{_f(rep['mean_rho_delta']):>18}")
    print("  * rho of smoke_load vs (next-48h PM2.5 minus previous-24h PM2.5): removes season-long trends and day-to-day autocorrelation.")
    rho, frp, delta = rep["mean_rho"], rep["mean_rho_frp"], rep["mean_rho_delta"]
    if rho is not None and delta is not None:
        if rho < 0.15 and delta < 0.15:
            verdict = f"NO demonstrable skill (mean rho {_f(rho)}, vs change {_f(delta)}). Do not claim the model works from this run."
        elif rho < 0.15:
            verdict = ("MIXED: some signal in day-to-day changes but it does not track PM2.5 levels. "
                       "Inconclusive; do not claim the model works from this run.")
        elif frp is not None and rho <= frp + 0.05:
            verdict = "has some skill but does NOT clearly beat fire counts alone: the wind is not yet adding value."
        elif delta < 0.15:
            verdict = "tracks the level of PM2.5 but not day-to-day changes: possibly just seasonal trend. Treat with suspicion."
        elif not _consistent(rep["cities"], "rho"):
            good = sum((c["rho"] or 0) >= 0.15 for c in rep["cities"].values())
            verdict = (f"positive on average, but only {good} of {len(rep['cities'])} cities show it, so one city is probably driving the mean. "
                       "Not evidence the model works.")
        else:
            verdict = "adds value over fire counts alone and predicts changes in PM2.5."
        if min(c["n"] for c in rep["cities"].values()) < 20:
            verdict += " (Under 20 days per city, so this is inconclusive either way.)"
        print(f"  -> {verdict}")

    if rep.get("n_met_rows"):
        print("\nDoes smoke add anything beyond the weather?  (ventilation = boundary-layer height x wind: stagnant air traps smoke)")
        print(f"  {'city':<11}{'ventilation':>12}{'smoke index':>13}   {'smoke | vent**':<22}{'vent vs chg*':>13}{'index vs chg*':>15}{'AUC vent':>10}{'AUC index':>11}")
        for city, c in rep["cities"].items():
            ci = f" [{_f(c['rho_partial_ci'][0])}, {_f(c['rho_partial_ci'][1])}]" if c["rho_partial_ci"] else ""
            print(f"  {city:<11}{_f(c['rho_vent']):>12}{_f(c['rho_index']):>13}   {(_f(c['rho_partial']) + ci):<22}"
                  f"{_f(c['rho_vent_delta']):>13}{_f(c['rho_index_delta']):>15}{_f(c['auc_vent']):>10}{_f(c['auc_index']):>11}")
        print(f"  {'mean':<11}{_f(rep['mean_rho_vent']):>12}{_f(rep['mean_rho_index']):>13}   {_f(rep['mean_rho_partial']):<22}"
              f"{_f(rep['mean_rho_vent_delta']):>13}{_f(rep['mean_rho_index_delta']):>15}{_f(rep['mean_auc_vent']):>10}{_f(rep['mean_auc_index']):>11}")
        print("  ventilation / smoke index: rho against next-48h PM2.5 (index = smoke_load / ventilation). * against the change vs the previous 24 h.")
        print("  ** partial rho: smoke_load vs PM2.5 after removing what ventilation explains. This is the fair test of the fire model.")
        part, idx, vent = rep["mean_rho_partial"], rep["mean_rho_index"], rep["mean_rho_vent"]
        if part is not None:
            if part < 0.15:
                msg = f"once ventilation is accounted for, smoke load explains little (mean partial rho {part:.2f})."
            elif not _consistent(rep["cities"], "rho_partial"):
                good = sum((c["rho_partial"] or 0) >= 0.15 for c in rep["cities"].values())
                msg = (f"mean partial rho is {part:.2f}, but only {good} of {len(rep['cities'])} cities show it: "
                       "likely one city driving the mean, so smoke is not shown to add beyond ventilation.")
            else:
                msg = f"smoke carries information beyond ventilation (mean partial rho {part:.2f}, consistent across cities)."
            if idx is not None and vent is not None:
                msg += f" Combining them (load / ventilation) {'beats' if idx > vent + 0.05 else 'does NOT beat'} ventilation alone ({idx:.2f} vs {vent:.2f})."
            print(f"  -> {msg}")

    if rep.get("filter_compare"):
        print("\nFire filter comparison (same days, same model params)")
        print(f"  {'filter':<8}{'kept':>7}{'mean rho':>10}{'vs change':>11}{'mean AUC':>10}{'days >= MODERATE':>18}")
        for c in rep["filter_compare"]:
            kept = f"{c['kept_frac']:.0%}" if c["kept_frac"] is not None else "n/a"
            print(f"  {c['mode']:<8}{kept:>7}{_f(c['mean_rho']):>10}{_f(c['mean_rho_delta']):>11}{_f(c['mean_auc']):>10}"
                  f"{c['moderate_plus_days']:>18}")
        print("  (params were tuned with the main filter, which slightly favours it; differences under ~0.1 are noise at this sample size)")

    print(f"\nEvent detection: event = next-48h mean PM2.5 >= {rep['event_pm25']:g} ug/m3  (AUC: 0.5 = chance, 1 = perfect)")
    print(f"  {'city':<11}{'event rate':>11}{'AUC model':>11}{'fires only':>11}{'persistence':>13}")
    for city, c in rep["cities"].items():
        print(f"  {city:<11}{c['event_rate']:>10.0%}{_f(c['auc']):>11}{_f(c['auc_frp']):>11}{_f(c['auc_persist']):>13}")
    for lv, d in rep["detection"].items():
        print(f"  alert at >= {lv:<8} precision {_f(d['precision'])}  recall {_f(d['recall'])}  F1 {_f(d['f1'])}"
              f"   (tp {d['tp']}, fp {d['fp']}, fn {d['fn']})")

    print("\nObserved PM2.5 by predicted level (should rise from LOW to SEVERE)")
    for lv, d in rep["by_level"].items():
        ev = f"{d['event_rate']:.0%}" if d["event_rate"] is not None else "n/a"
        print(f"  {lv:<9} n={d['n']:<4} mean {_f(d['mean_obs'], 0):>5}   median {_f(d['median_obs'], 0):>5}   event days {ev}")

    t = rep["timing"]
    print(f"\nTiming (event days predicted >= MODERATE, n={t['n']}): predicted peak vs hour of observed PM2.5 maximum,"
          f" median error {_f(t['median_abs_err_h'], 1)} h, 75th pct {_f(t['p75_abs_err_h'], 1)} h")

    if rep["tuning"]:
        print("\nTop tuning results (train period, mean per-city rho of load vs change in PM2.5)")
        for t in rep["tuning"][:5]:
            print(f"  rho {_f(t['mean_rho'])}  radius {t['radius_km']:g}  decay {t['decay_h']:g}  wind x{t['wind_scale']:g}")

    sug = rep["suggested_thresholds"]
    print("\nSuggested constants for layers/common/python/common/model.py (fit on the data above - confirm on another season):")
    if rep["tuning"] and (rep["tuning"][0]["mean_rho"] or 0.0) < 0.15:
        print("  (tuning found no setting with training rho >= 0.15, so there are no radius/decay/wind-scale constants worth adopting)")
    elif rep["tuning"]:
        print(f"  ARRIVAL_RADIUS_KM = {p['radius_km']:g}\n  DECAY_H = {p['decay_h']:g}\n  WIND_SCALE = {p['wind_scale']:g}")
    if all(s is not None for s in sug):
        print(f"  LOAD_THRESHOLDS = ({sug[0]:g}, {sug[1]:g}, {sug[2]:g})   # best-F1 cut-offs for PM2.5 >= {', '.join(f'{x:g}' for x in rep['pm_levels'])}")
    else:
        print(f"  LOAD_THRESHOLDS: no usable fit at PM2.5 levels {rep['pm_levels']} (too few events, or no cut-off beats alerting every day)")
    print()


def main(argv=None):
    args = parse_args(argv)
    rep = run(args)
    rows = rep.pop("_rows")
    print_report(rep)
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        print(f"wrote {args.out}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows({**r, "issue": r["issue"].isoformat()} for r in rows)
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
