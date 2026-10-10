# SmokeShield

**When will crop-fire smoke reach your city, and what should schools do about it?**

Fires in Punjab and Haryana -> wind -> smoke arriving in Delhi ~6-24 hours later. SmokeShield turns that chain into a
forecast window per city and a plain-language action plan for school administrators (English / Hindi).

WeMakeDevs 2026, event 02 - track **Air** (stubble burning, school safety on bad days).

## How it works

```
EventBridge (hourly)
  -> Lambda: ingest -- NASA FIRMS fires + Open-Meteo wind + Open-Meteo/CAMS PM2.5
        |-> S3 (raw snapshots - the back-test dataset)
        |-> deterministic model (layers/common/python/common/model.py)
        |-> DynamoDB (risk record per city per hour)  --> SNS email on escalation to HIGH/SEVERE
  API Gateway (HTTP API) -> Lambda: api       GET /cities  /risk  /risk/{city}
                         -> Lambda: advisory  GET /advisory/{city}?lang=en|hi
                                 Strands Agents SDK + Amazon Bedrock, cached in DynamoDB
  frontend/ (static, Leaflet) -> Amplify Hosting
```

**The model** bins active fires into ~25 km cells, releases one air parcel per cell, advects it along the hourly
forecast wind for 48 h, and records when it first passes within 50 km of a city. Each cell contributes its fire
radiative power, discounted by travel time. It is deterministic and unit-tested; the LLM never computes numbers.

**The agent** (Strands) has two tools: `get_smoke_forecast` (the model output) and `get_school_guidance` (a fixed
table in `guidance.py`). It only phrases the result. If Bedrock is unavailable the API returns a template advisory,
so the demo never breaks.

**The fire filter** (`common/filters.py`) drops detections that are probably not crop-residue burning before they are counted:
fires inside urban cores (`URBAN_EXCLUSIONS` in `cities.py`) and fires on cells that burn repeatedly in the non-burning months
(landfills, kilns, industry; `static_sources.json`, built by `scripts/build_static_mask.py` from Jan-Mar + Jul-Sep 2025 FIRMS data).
Modes: `none | urban | static | all`; the Lambda uses `all` (`FIRE_FILTER` in `template.yaml`). It is not land cover.
On the 2025 season it removed only ~3% of detections and did not measurably change back-test results (`--compare-filters`),
so keep it as cheap hygiene, not as a source of skill. Rebuild the mask with `FIRMS_MAP_KEY=... python scripts/build_static_mask.py`
and eyeball the printed top cells (they should be industrial / landfill sites) before committing it.

**Ventilation** (`ventilation_stats` in `model.py`): boundary-layer height x 10 m wind, in m2/s, from Open-Meteo, averaged over the next 48 h
as the mean of 1/VI so a single stagnant night counts. Every risk record carries `ventilation` (`vi_mean`, `vi_min`, `inv_vi`) and
`smoke_index = smoke_load / ventilation`. It is context only: `risk_level` is **not** adjusted by it, because the back-test has not shown that
combining them helps. The ingest Lambda also snapshots `met.json` so future back-tests can score it on real forecasts.

**Air-mixing (stagnation) label** (`stagnation_label` in `model.py`): `POOR` below 165 m2/s of effective 48 h ventilation (1 / mean(1/VI)),
`GOOD` from 240 m2/s, `MODERATE` in between. These cut-offs are the pooled 30th / 70th percentiles of Oct 20 - Nov 25, 2017-2019, and they were checked
leave-one-season-out (cut-offs fitted on two seasons, scored on the third). For Delhi and Gurugram, held-out PM2.5 averaged 249 / 192 / 175 ug/m3 for
POOR / MODERATE / GOOD (days >= 150: 94% / 76% / 59%), ordered correctly in all three seasons. What it does *not* show:
- **Only Delhi and Gurugram are validated** (`STAGNATION_VALIDATED` in `cities.py`). Jaipur showed no relationship; Chandigarh and Ludhiana have no usable data.
  Other cities display the label marked "indicative only", and the advisory ignores it there.
- MODERATE vs GOOD barely differ on the worst days (share >= 250: 15% vs 15%), so POOR is the label that carries the evidence. Only POOR adds advice.
- Cut-offs came from ERA5 reanalysis; live forecast boundary-layer heights can differ. Re-fit once `met.json` snapshots exist (`backtest.py --snapshots`).
- The label does not change `risk_level`; it is a separate signal shown beside it and added to the advisory (template and Strands agent) as one note and one action.

### Honest limitations (say these in the demo)
- 10 m wind on a coarse grid; real transport is through the boundary layer. `WIND_SCALE` is a calibration knob.
- One release time: fires keep burning, so real exposure lasts longer than the window shown.
- No plume spread or chemistry. Risk thresholds in `model.py` (`CALIBRATE`) are placeholders until back-tested.
- CAMS PM2.5 over India reads low; it is a baseline hint, not ground truth.
- `guidance.py` must be checked against official CPCB / GRAP / state education-department guidance before you present it.

## Run it locally (no AWS account)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                                                   # 20+ tests, all offline
python scripts/run_local.py --write-mock                 # sample fires + synthetic NW wind, writes frontend/mock.json
python -m http.server 8000 --directory frontend          # live data: http://localhost:8000   offline demo: http://localhost:8000/?mock=1
```

Live data without AWS: get a free key at https://firms.modaps.eosdis.nasa.gov/api/map_key/ then
`FIRMS_MAP_KEY=... python scripts/run_local.py --live --write-mock`.
Try different winds offline: `python scripts/run_local.py --wind-from 270 --wind-kmh 25`.

The Strands agent locally (needs AWS credentials + Bedrock model access): `python scripts/run_local.py --agent`.

## Back-test (the credibility slide)

`scripts/backtest.py` replays past fire seasons through the model, asks whether PM2.5 in the next 48 h actually rose when
it said it would, and compares against two baselines: **fires only (no wind)** and **persistence (today's PM2.5)**. If the
model can't beat fires-only, the wind adds nothing and you should know before the judges do.

```bash
python scripts/backtest.py --demo        # synthetic season: proves the harness runs, numbers mean nothing

# last season, real data. Needs FIRMS_MAP_KEY; --truth-csv = observed PM2.5 (columns: city,timestamp,pm25)
python scripts/backtest.py --start 2025-10-20 --end 2025-11-25 --truth-csv data/pm25.csv --truth-utc-offset 5.5 --tune --out report.json
```

- **Truth:** best is a CPCB / OpenAQ export as CSV. Without `--truth-csv` it falls back to CAMS model output via Open-Meteo, which is
  keyless but not a measurement and reads low over India, so use it for a first pass only.
- **`--tune`** grid-searches `radius / decay / wind-scale` on the first 60% of days and reports on the remaining 40%, so the numbers are
  out-of-sample. It prints the constants to paste into `model.py`, plus best-F1 `LOAD_THRESHOLDS` for the PM2.5 levels in `--pm-levels`.
- **Weather test:** with meteorology available the report adds a "Does smoke add anything beyond the weather?" section (ventilation alone,
  `load / ventilation`, and the partial correlation of smoke with PM2.5 after controlling for ventilation). `--no-met` skips it;
  `--objective partial` tunes on the partial correlation. Verdicts require the effect in at least 2/3 of cities, so one city can't carry a result.
- **Fire filter:** applied by default (`--filter none|urban|static|all`); add `--compare-filters` to score every mode on the same days.
- **Results so far (be upfront about these):**
  - *2019 season, measured CPCB PM2.5, Delhi / Gurugram / Chandigarh / Jaipur, 37 days:* weak, not yet convincing. Observed PM2.5 does rise
    with predicted level (LOW 134 -> MODERATE 145 -> HIGH 165 -> SEVERE 192 ug/m3; SEVERE days were events 3 of 4 times), but mean rho is
    0.09 and rho against the day-to-day *change* in PM2.5 is 0.16. Raw fire counts without wind rank event days at least as well as the
    model (AUC 0.65 vs 0.46 in Delhi), and "yesterday's PM2.5" beats both (rho ~0.56). Tuned out-of-sample on 15 days: no skill; nothing
    to adopt. Fire filter (`--compare-filters`): no effect (removes ~1% in 2019, ~3% in 2025).
  - *Three measured seasons (2017, 2018, 2019; Oct 20 - Nov 25; Delhi / Gurugram / Jaipur; default untuned params; the Kaggle file ends July 2020 so
    there is no 2020 season).* Spearman rho against next-48h mean PM2.5:

    | | 2017 | 2018 | 2019 |
    |---|---|---|---|
    | Ventilation alone (mean over cities) | +0.39 | +0.58 | +0.08 |
    | - Delhi / Gurugram | +0.63 / +0.32 | +0.56 / +0.55 | +0.28 / +0.20 |
    | Smoke model (fires + wind) | -0.18 | -0.24 | +0.09 |
    | Smoke after controlling for ventilation (partial) | -0.10 | +0.05 | +0.09 |
    | "Yesterday's PM2.5" | +0.39 | +0.42 | +0.56 |

    Ventilation is positively related to PM2.5 in Delhi and Gurugram in all three seasons (stagnant air = dirtier air). The smoke model is
    negative in two of three seasons and adds nothing once weather is removed. Why it goes negative: smoke load is itself a function of wind, and
    in 2017-18 it correlates -0.25 to -0.54 with stagnation, so it tends to be "high" on windy, clean days. Raw fire counts without wind
    did better than the model in 2018 (rho +0.48 Delhi, +0.44 Gurugram), which points at the wind-routing step, not the fire data.
    A tuned run once looked positive: that was one city (Jaipur) on 15 days with training rho ~0.02, i.e. noise, and the report now flags it.
  - *2025 season, CAMS model as truth:* no demonstrable skill either.
  - Reading: day-to-day PM2.5 in Delhi's November is mostly weather (stagnation, inversions) plus Diwali fireworks; the fire model has not been shown to add
    to that. A stagnation warning from ventilation looks more defensible than a smoke-arrival forecast. Next experiments: score on real
    forecasts via `--snapshots`, try ward-level exposure, and replace the 10 m wind routing. Don't present the smoke model as validated.
- **Wind caveat:** past-season mode uses ERA5 reanalysis (what the wind actually did), an upper bound on live skill. Once the deployed
  stack has run for a while, `aws s3 sync s3://<RawBucketName>/raw data/raw` and run `--snapshots data/raw` to score the real
  forecasts the system issued.
- Fires and wind responses are cached in `.cache/backtest/`, so re-runs are instant. FIRMS archive (`VIIRS_SNPP_SP`) lags ~3 months;
  for a season that ended more recently pass `--firms-source VIIRS_SNPP_NRT`.
- Small samples: a season is ~35 days per city. The report prints block-bootstrap confidence intervals and warns under 20 days;
  report them, not just the point estimates.

## Deploy to AWS

Prereqs: AWS account (Free Tier credits are fine), AWS CLI configured, [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html), Docker or `--use-container` if your local Python is not 3.12.

1. **Bedrock:** submit Anthropic's one-time first-use form (console: Bedrock -> Model catalog -> a Claude model, or
   `aws bedrock put-use-case-for-model-access`), then note the model's inference-profile ID (`aws bedrock list-inference-profiles`).
   `aws bedrock get-foundation-model-availability --model-id anthropic.<model>` should then report `AUTHORIZED`.
   Brand-new accounts can be blocked (`Your account is currently being verified`, later `ValidationException: Operation not allowed`) until
   AWS Support unblocks them; the app still works without Bedrock and falls back to a template advisory.
2. Deploy:
   ```bash
   sam build --use-container
   sam deploy --guided --parameter-overrides FirmsMapKey=<key> BedrockModelId=<id> AlertEmail=you@example.com
   ```
3. Warm it: `aws lambda invoke --function-name <IngestFunctionName output> out.json` (otherwise wait for the hourly schedule).
4. Put the `ApiUrl` output into `frontend/config.js` (already done for the current stack; with `API_BASE` empty, or `?mock=1` on the URL, the page
   runs on `mock.json` instead), then host `frontend/` on **Amplify Hosting** (Deploy without Git -> drag the folder in).
   **Heads-up: the current Amplify app lives in `eu-north-1` (Stockholm), not `us-east-1` like the rest of the stack.** Switch the console region
   (top right) to find it, and pass `--region eu-north-1` to every `aws amplify` command. Static hosting doesn't care where it lives, but teardown does
   (see below).
5. Confirm the SNS subscription email if you set one. `AllowOrigins` in `template.yaml` is already restricted to the Amplify page and localhost
   (8000, 8765); add your own domain there if you attach one, then redeploy.

**Redeploying later (Windows):** build outside OneDrive, because syncing locks `.aws-sam` and the build fails with "Access is denied".
```bash
sam build --use-container --build-dir C:\Users\<you>\sam-build\smoke-shield
sam deploy --template-file C:\Users\<you>\sam-build\smoke-shield\template.yaml --stack-name smoke-shield --region us-east-1 --resolve-s3 --capabilities CAPABILITY_IAM
```
Parameters you don't repeat (FIRMS key, model ID) keep their stored values. Add `--no-execute-changeset` first to preview what would change.

**Costs:** Lambda, DynamoDB, S3, API Gateway, SNS email stay inside the free tier at this scale. Bedrock is pay-per-token and
is the only meaningful cost; advisories are cached per city per ingest run, so it is a few calls per hour.

### Updating the hosted page from the command line
After changing `frontend/`, rebuild the zip (contents of `frontend/` at the archive root) and deploy it:
```powershell
Compress-Archive -Path frontend\* -DestinationPath dist\smokeshield-frontend.zip -Force
$dep = aws amplify create-deployment --app-id d1nrk1hn0hdamc --branch-name main --region eu-north-1 | ConvertFrom-Json
Invoke-WebRequest -Method Put -Uri $dep.zipUploadUrl -InFile dist\smokeshield-frontend.zip -ContentType application/zip
aws amplify start-deployment --app-id d1nrk1hn0hdamc --branch-name main --job-id $dep.jobId --region eu-north-1
```
Confirm it landed with `aws amplify list-jobs --app-id d1nrk1hn0hdamc --branch-name main --region eu-north-1` (a new job, status `SUCCEED`).
A job count that doesn't go up means the upload never registered.

### Monitoring and what to do when an alarm fires
`aws cloudformation describe-stacks --stack-name smoke-shield --region us-east-1 --query "Stacks[0].Outputs[?OutputKey=='DashboardUrl'].OutputValue" --output text`
prints the dashboard link (`smoke-shield-ops`). Five alarms notify the SNS ops topic (`OpsTopicArn` output):

| Alarm | Means | First thing to do |
|---|---|---|
| `IngestErrorsAlarm` | The hourly ingest raised an error | Read the ingest log group (`aws logs tail <group> --since 2h`); FIRMS or the wind feed is the usual cause |
| `IngestStaleAlarm` | No ingest run for two hours (missing data counts as failure) | Check the EventBridge rule is enabled and the function isn't throttled |
| `IngestNoFiresAlarm` | Three runs in a row saw zero fire detections in the last 24 h (the run "succeeded" but saw nothing) | Check the FIRMS key and API (`curl` the area URL with `day_range=2`); see the 24-hour-window note below |
| `ApiServerErrorsAlarm` | 3+ API 5xx errors in five minutes | Check the api and advisory log groups |
| `IngestDLQAlarm` | A failed run is waiting in the dead-letter queue | Read it: `aws sqs receive-message --queue-url <IngestDeadLetterQueueUrl>`, then fix and re-run `aws lambda invoke` |

The ingest also emits custom metrics every hour (namespace `SmokeShield`: `FiresRaw`, `FiresUsed`, `CitiesScored`, `CitiesPoorMixing`, `CitiesHighSmoke`,
`CitiesMissingWeather`, `AlertsSent`) as a CloudWatch embedded-metric-format log line (`common/observability.py`), so there is no SDK call or extra permission.
**No email is attached by default.** To get alarm emails, redeploy with `--parameter-overrides OpsEmail=you@example.com` and confirm the SNS message.
To test the alarm path without breaking anything, force one: `aws cloudwatch set-alarm-state --alarm-name <name> --state-value ALARM --state-reason test`,
then read `aws cloudwatch describe-alarm-history --alarm-name <name> --history-item-type Action` for "Successfully executed action ...", and set it back to `OK`.
Log groups keep 30 days. The log groups created automatically before this was added (named `/aws/lambda/smoke-shield-...`) remain with no expiry and are not part of the stack.

### The fire window is the last 24 hours, not "today" (read this before touching the FIRMS call)
FIRMS' `day_range` counts UTC calendar days. `day_range=1` is "since 00:00 UTC today", and the VIIRS pass over India (~08:00 UTC) only lands hours later, so a
run between 00:00 and ~10:00 UTC (05:30-15:30 IST) sees nothing. The ingest therefore requests 2 days (`fetch_fires_csv`) and `parse_fires(csv, now)` keeps
detections acquired within the previous 24 h (`FIRE_WINDOW_HOURS`), dropping anything older or dated in the future (30-minute skew allowance). This matches the
back-test, which issues forecasts at 00:00 UTC from the previous full day of fires.
**Known data gap:** the hourly snapshots saved by runs between 2026-10-10 00:19Z and the fix contain no detections. `backtest.py --snapshots` skips snapshots with
zero detections by default (`--keep-empty-snapshots` includes them) and applies the same 24-hour window relative to each snapshot's own issue time.

### Where everything lives, and how to tear it down
| Piece | Region | How to remove it |
|---|---|---|
| CloudFormation stack `smoke-shield` (3 Lambdas + layer, API Gateway, DynamoDB, raw-snapshot S3 bucket, SNS topics, SQS dead-letter queue, 5 alarms, dashboard, log groups, EventBridge rule, IAM roles) | `us-east-1` | Empty the raw bucket first (CloudFormation can't delete a non-empty bucket): `aws s3 rm s3://<RawBucketName> --recursive`, then `sam delete --stack-name smoke-shield --region us-east-1` |
| Amplify app `smokeshield` (the hosted map) | **`eu-north-1`** | Not part of the stack, so `sam delete` leaves it. `aws amplify delete-app --app-id d1nrk1hn0hdamc --region eu-north-1`, or console -> switch region to Stockholm -> Amplify -> delete app |
| SAM's shared artifact stack `aws-sam-cli-managed-default` | `us-east-1` | Empty its bucket, then delete the stack (CloudFormation console). It is shared by any other SAM projects in the account |
| IAM user `smokeshield-deploy` and its access key | global | Console -> IAM: delete the key, then the user |
| Local build output | your machine | `C:\Users\<you>\sam-build\smoke-shield` and the `.aws-sam` folder are safe to delete |

`<RawBucketName>` is a stack output: `aws cloudformation describe-stacks --stack-name smoke-shield --region us-east-1 --query "Stacks[0].Outputs"`.

## AWS usage (for the submission)
Strands Agents SDK (open source) - Amazon Bedrock - Lambda - API Gateway - DynamoDB - S3 - EventBridge - SNS - SAM - Amplify Hosting.

## Roadmap / TODO
- [x] `scripts/backtest.py` written, [x] crop-fire filter written. [ ] Still to do: run the back-test with measured PM2.5 (CPCB `city_hour.csv` for 2019, or a CPCB 2025 export) before tuning constants or claiming skill.
- [ ] If the model still shows no skill on measured data: try ward-level exposure instead of a 50 km radius, a boundary-layer wind average, and a land-cover (cropland) mask in place of the heuristic filter.
- [ ] Ward-level risk and subscribe-your-school form (DynamoDB + SNS).
- [ ] Telegram / WhatsApp alert channel (SNS SMS to India needs DLT registration).
- [ ] Multi-level wind (boundary-layer average) instead of 10 m.
