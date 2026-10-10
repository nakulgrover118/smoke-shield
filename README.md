# SmokeShield

**An early-warning map for Indian schools: when will crop-fire smoke reach my city, and is the air about to stop moving?**

WeMakeDevs 2026, event 02 · Track: **Air** (stubble burning, school safety on bad days)

**Live demo:** https://main.d1nrk1hn0hdamc.amplifyapp.com  ·  offline sample scenario: add `?mock=1` to the URL
**API:** https://3oxq6ij166.execute-api.us-east-1.amazonaws.com (`/cities`, `/risk`, `/risk/{city}`, `/advisory/{city}?lang=en|hi`)
*(Hosted on a personal AWS account and may be taken down after the event; the whole stack redeploys from this repo with `sam deploy`.)*

---

## The problem
Every October-November, smoke from crop-residue fires in Punjab and Haryana drifts toward Delhi-NCR, and on the worst days a school has to decide
tonight whether tomorrow's assembly, PE class and bus pick-ups are safe. Today's AQI tells them how bad the air *is*. They need to know what is *coming*,
in words they can act on.

## What SmokeShield does
Every hour it combines NASA satellite fire detections with weather forecasts, and shows five cities on a map with two separate signals:

| Signal | What it tells a school | How much we trust it |
|---|---|---|
| **Air mixing** (`POOR` / `MODERATE` / `GOOD`) | Over the next 48 h, will the air stay still and trap pollution near the ground? | **Tested on held-out seasons** for Delhi and Gurugram (see below) |
| **Smoke arrival** (`LOW` to `SEVERE`, with an arrival window in hours) | Will smoke from upwind crop fires reach us, and roughly when? | **Experimental. Not validated.** We say so on every page we can. |

Each city opens with a one-line **recommendation** in plain words ("Move strenuous sport indoors... prefer midday or afternoon for outdoor activity"),
followed by the two signals and a fuller advisory. Air mixing leads: it is the headline badge in the city list and the colour on the map, and the smoke estimate
sits below it, labelled experimental. **Everything is available in English and Hindi** (हिन्दी), including city names, the recommendation and the advisory.
Today the advisory text comes from reviewed templates in both languages; once our Bedrock access is enabled, a Strands agent writes it instead, and the
templates remain as the fallback. On a phone the cities become a swipeable strip so the recommendation is on the first screen.

## Does it work? What the data says
We built a back-test harness and ran it on three real seasons (Oct 20 - Nov 25, 2017-2019) of measured CPCB PM2.5, with confidence intervals and
three baselines: raw fire counts, yesterday's PM2.5, and weather alone.

**Air mixing: yes, for Delhi and Gurugram.** Cut-offs were fitted on two seasons and scored on the third, in all three rotations:

| Predicted air mixing | Mean PM2.5 next 48 h | Days at or above 150 µg/m³ |
|---|---|---|
| POOR | 249 µg/m³ | 94% |
| MODERATE | 192 µg/m³ | 76% |
| GOOD | 175 µg/m³ | 59% |

The ordering held in every held-out season. Jaipur showed no relationship, and Chandigarh and Ludhiana lack usable data, so only Delhi and Gurugram
are labelled "validated"; other cities show the label as *indicative only*.

**Smoke arrival: not shown to work.** Rank correlation with PM2.5 was -0.18 (2017), -0.24 (2018) and +0.09 (2019), and once weather is removed it adds
nothing. We found out *why*: the model's smoke load depends on wind speed, so on windy clean days it is high and on stagnant dirty days it is low. We kept the
feature, flagged it as experimental, and wrote down the next experiments instead of hiding it.

**Limits we are upfront about:** three seasons, one input data source, wind from reanalysis (an upper bound on live forecast skill), cut-offs not yet
re-checked on real forecasts (the deployed system now saves hourly snapshots so that can happen), and **PM2.5 is driven by more than crop smoke** (traffic,
dust, Diwali fireworks). The advisory text is not medical advice and needs review against official guidance before real-world use.

## Architecture (AWS)
```
EventBridge (hourly)
  └─ Lambda ingest ──► NASA FIRMS fires · Open-Meteo wind, weather, PM2.5 baseline
        ├─► S3        raw snapshots (the dataset for future back-tests)
        ├─► DynamoDB  one risk record per city per hour
        ├─► SNS       alert when a city's smoke risk reaches HIGH
        ├─► SQS       dead-letter queue: a run that still fails after retry is kept for 14 days
        └─► CloudWatch  custom metrics (fires used, cities on poor mixing, missing weather) via embedded metric format
API Gateway (HTTP API)
  ├─ Lambda api       /cities  /risk  /risk/{city}
  └─ Lambda advisory  /advisory/{city}  ── Strands Agents SDK ─► Amazon Bedrock (cached per city per hour)
Amplify Hosting ── static map (Leaflet) ── calls the API
CloudWatch ── 5 alarms ──► SNS ops topic      dashboard: ingest health, data volume, API traffic, queue depth
```
**AWS services:** Lambda (3 functions + a shared layer), API Gateway, DynamoDB, S3, EventBridge, SNS, SQS, CloudWatch (alarms, dashboard, custom
metrics, log retention), Amplify Hosting, CloudFormation via SAM, Bedrock, and the open-source **Strands Agents SDK**. Infrastructure is one
`template.yaml`; deploy time is about 3 minutes.

**How we know it is running (and when it isn't):** five alarms cover the ways this fails quietly, each notifying an SNS ops topic: the hourly ingest raising an
error; the ingest *silently not running for two hours* (missing data counts as failure, so a disabled schedule can't hide); the ingest *running but seeing zero
fires three runs in a row*; the public API returning 5xx errors; and a failed run parked in the dead-letter queue. A CloudWatch dashboard shows all of it on one
page. We tested the alarm-to-SNS path by forcing an alarm and reading its action history, not just by creating it.

**A bug we found in production, and what it taught us:** the live ingest asked NASA for `day_range=1`, which means "today so far in UTC", not "the last 24 hours".
The satellite passes over India around 08:00 UTC and its data lands hours later, so for about ten hours after 00:00 UTC (05:30-15:30 IST, the school morning)
the smoke estimate silently saw zero fires. We caught it from the saved hourly snapshots, not from an error, because nothing had failed. The fix requests two
days and keeps exactly the last 24 hours by acquisition time; the "no fires three runs in a row" alarm exists so this can't recur unnoticed, and the back-test
now skips empty snapshots instead of scoring silence as "no fires". The air-mixing signal, which comes from weather data, was never affected.

**Honest status of the agent:** the Strands agent and its three tools are written and exercised in tests, and the advisory function falls back to a template
whenever the model can't be reached. Our brand-new AWS account is still being unblocked for Bedrock, so **the live site currently shows the template advisory (English and Hindi), not agent-written text**.
The model ID is already configured, so it switches on without a redeploy once access is granted.

## What is in the repo
| Path | Contents |
|---|---|
| `layers/common/python/common/` | The model (`model.py`), crop-fire filter, data fetchers, guidance text, storage helpers: pure Python, no AWS imports in the maths |
| `functions/` | The three Lambda handlers and the Strands agent |
| `frontend/` | The map (single HTML file, no build step) |
| `scripts/backtest.py` | The validation harness: baselines, bootstrap CIs, out-of-sample tuning, guards against over-claiming |
| `tests/` | 185 tests (model physics, the 24-hour fire window, handlers, English/Hindi guidance, the school planner's status matrix, back-test statistics, the verdict logic, template lint, dashboard JSON) |
| `template.yaml` | The whole AWS stack |
| `docs/DEVELOPMENT.md` | Full developer notes: running offline, deploying, all back-test commands and results |

## Things we are proud of
- **The honest back-test.** When the first results were bad we didn't tune until they looked good. We added baselines, an out-of-sample split, and verdict logic
  that refuses to call a result a win when one city carries the average. Several bugs in our own reporting were found and fixed that way (each has a regression test).
- **It degrades gracefully.** No Bedrock, no air-quality feed, no weather feed, and the forecast still goes out.
- **It tells us when it breaks.** Alarms, a dead-letter queue and a dashboard, with the "stopped silently" failure mode covered explicitly.
- **It runs offline.** `python scripts/run_local.py --write-mock` plus any static server reproduces the demo with no AWS account.

## Run it yourself
```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                              # 185 tests, all offline
python scripts/run_local.py --write-mock            # sample fires + synthetic wind
python -m http.server 8000 --directory frontend     # http://localhost:8000/?mock=1
```
Deploying to your own AWS account is documented in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) (needs Docker, the SAM CLI and a free NASA FIRMS key).

## What's next
1. Score the saved hourly forecasts (`backtest.py --snapshots`) to re-check the air-mixing cut-offs on real forecasts, not reanalysis.
2. Replace the smoke-arrival routing with a regional fire index and test it against air mixing; the back-test already shows where the current one fails.
3. Add a measured-PM2.5 feed (CPCB) and ward-level exposure for more cities.
4. Review the advisory wording with school health guidance, then add Telegram/WhatsApp alerts (SNS SMS to India needs DLT registration).

## Data and credits
NASA FIRMS (VIIRS active fires) · Open-Meteo (weather, ERA5 reanalysis, CAMS air quality; CC BY 4.0) · CPCB hourly air quality via the Kaggle
"Air Quality Data in India (2015-2020)" dataset for validation · OpenStreetMap tiles · Leaflet · Strands Agents SDK and AWS SAM.
Built by Nakul Grover.
