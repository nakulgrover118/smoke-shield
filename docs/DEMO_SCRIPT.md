# SmokeShield: demo script (4 minutes + Q&A)

Goal of the demo: show a map that is useful, then earn trust by being straight about what is and isn't proven.
**Do not claim the smoke-arrival forecast works.** Judges who probe will find the weak spot; the strong move is to name it first.

## 30 minutes before
Run these once, in order. Everything below is a check, not a setup.

1. **Warm the data.** Make sure the latest hourly run is fresh:
   ```bash
   aws lambda invoke --function-name <IngestFunctionName> out.json
   ```
2. **Check the API:** open `https://3oxq6ij166.execute-api.us-east-1.amazonaws.com/risk` and confirm 5 cities with a recent `generated_at`.
3. **Check the advisory in both languages:** open `.../advisory/delhi?lang=en` and `.../advisory/delhi?lang=hi`. `"source":"fallback"` is expected until
   Bedrock is unblocked, and the Hindi one should be in Devanagari (it is a reviewed template). If either says `"source":"agent"`, Bedrock is on: say so in the demo.
4. **Open four browser tabs, in this order:**
   - Tab 1: live site `https://main.d1nrk1hn0hdamc.amplifyapp.com`
   - Tab 2: demo scenario `https://main.d1nrk1hn0hdamc.amplifyapp.com/?mock=1`
   - Tab 3: the repo README, scrolled to **Does it work? What the data says**
   - Tab 4: the AWS console, CloudWatch dashboard `smoke-shield-ops` (https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=smoke-shield-ops).
     Have the CloudFormation stack `smoke-shield` (Resources tab) open in a fifth tab as the backup view.
5. **Look at the live map right now.** In early October it is usually quiet (every city LOW, air mixing GOOD). That is fine and honest. Peak burning is late October to November.
6. **Backup:** take screenshots of tab 1 and tab 2 in case the wifi dies. Know that `?mock=1` needs no AWS at all.

## The talk (4:00)

### 0:00 - 0:30 The problem
**SAY:** "Every October and November, smoke from crop fires in Punjab and Haryana drifts toward Delhi. A school principal has to decide tonight whether tomorrow's
assembly, PE class and buses are safe. Today's AQI tells them how bad the air *is*. They need to know what's *coming*, in words they can act on. That's SmokeShield."
**DO:** Tab 1, the live map. Say nothing about the data yet.

### 0:30 - 1:30 The live map
**DO:** Point at the five city markers, then click **Delhi**.
**SAY:** "Every hour, an AWS pipeline pulls NASA's satellite fire detections and weather forecasts, and scores five cities. The badge you see first is air mixing."
**DO:** Point at the **Today's recommendation** card.
**SAY:** "This is what a school actually reads: one sentence. Today it says no smoke precautions are needed, and that's the honest answer on a quiet day."
**DO:** Point at the **Air mixing** section.
**SAY:** "Air mixing is boundary-layer height times wind. Low means the air is stagnant and traps pollution near the ground. It's GOOD right now, which is why
the map is quiet. I'll show you a bad day in a second."
**DO:** Point at the evidence line in that section.
**SAY:** "And it tells you how much to trust it. In past Delhi-NCR data, days with poor mixing averaged about 40% higher PM2.5."
**DO:** Point at the **Crop-fire smoke estimate** section and its grey caveat.
**SAY:** "The smoke estimate sits below, and the page says it's experimental. I'll explain why in a minute."
**DO:** Click **हिन्दी** at the top of the panel.
**SAY:** "The whole panel switches to Hindi: the city name, the recommendation and the advisory. These are reviewed templates today, so it works even without our AI model."

### 1:30 - 2:15 A bad day (sample scenario)
**DO:** Switch to Tab 2 (`?mock=1`). Click **Delhi**.
**SAY:** "This is a sample scenario with made-up weather, clearly labelled. Imagine a north-westerly day: the orange dots are fire clusters upwind of Delhi, smoke is
estimated to arrive in about 6 hours, and air mixing is POOR."
**DO:** Point at the recommendation card (amber, because it's a caution day).
**SAY:** "For a school, that becomes one plain sentence: move strenuous sport indoors, and because mixing is poor, prefer midday or afternoon for outdoor activity."
**SAY:** "The text under it comes from reviewed templates today. A Strands agent on Bedrock will write it instead; the code is built and tested, and our brand-new AWS
account is still being unblocked for Bedrock. The model is already configured, so it switches on without a redeploy, and the templates stay as the fallback."

### 2:15 - 3:15 The honest part (this is your strongest minute)
**DO:** Tab 3, the evidence tables.
**SAY:** "We didn't just build a forecast, we built a way to test it. Three real seasons of CPCB PM2.5, with baselines and out-of-sample splits."
**SAY:** "Result one: the air-mixing label works. Fitted on two seasons and tested on the third, poor, moderate and good days averaged 249, 192 and 175 micrograms,
and the order held in every held-out season. We only mark Delhi and Gurugram as validated; Jaipur showed nothing, so other cities say 'indicative only'."
**SAY:** "Result two: our smoke-arrival forecast does **not** beat the weather. We found out why. Its smoke load depends on wind speed, so on windy clean days it's high
and on stagnant dirty days it's low. So we label it experimental, and the next step is replacing the routing, not the claim."
**SAY:** "I'd rather show you a negative result I understand than a positive one I tuned into existence."

### 3:15 - 3:45 AWS and engineering
**DO:** Tab 4, the CloudWatch dashboard (or the architecture diagram in the README if the console is slow).
**SAY:** "One SAM template: EventBridge runs a Lambda every hour, data lands in DynamoDB and S3, API Gateway serves it, Amplify hosts the map, SNS sends alerts, and
the advisory runs the Strands Agents SDK on Bedrock. It deploys in about three minutes, and the hourly snapshots become next season's validation data."
**DO:** Point at the alarm strip at the top of the dashboard, then the "fire detections per run" graph.
**SAY:** "And we built it so we'd know when it breaks. Five alarms cover the quiet failures, including the ingest silently not running for two hours, because missing
data counts as failure. A failed run is kept in a dead-letter queue, and the ingest emits its own metrics: fires processed, cities on poor air mixing, weather feeds missing.
I tested the alarm path by forcing one and checking that it notified. There are 185 tests."

### 3:45 - 4:00 Close
**SAY:** "SmokeShield: the first signal tested on held-out data, the second honestly flagged as not there yet, and a pipeline already collecting the data to fix it.
Thank you."

## If something goes wrong
| Problem | What to do |
|---|---|
| Live site won't load or is blank | Use the `?mock=1` tab and say: "live is the same page against our AWS API; here's the same map on sample data." |
| Venue wifi is down | Use your screenshots of both tabs; run `python -m http.server 8000 --directory frontend` and open `localhost:8000/?mock=1` (works offline except map tiles). |
| The map is quiet and a judge says "nothing happens" | "Correct, today is a clean day, and the system says so. The demo scenario is what a burning-season day looks like." |
| Advisory says "fallback" | Say it first: "template today; Bedrock access is being enabled on the account." It is available in English and Hindi either way. |
| The recommendation card is missing on the live page | The ingest hasn't produced a fresh record since the last deploy. Run the ingest command from the checklist and reload. |
| A judge asks you to click something you haven't rehearsed | Stay on Delhi and the air-mixing panel; it's the strongest part. |

## Questions you should expect (and honest answers)
**Does the smoke forecast actually work?** No, not yet. Across three seasons its correlation with measured PM2.5 was -0.18, -0.24 and +0.09, and it adds nothing once weather is removed.
We found the cause (its load depends on wind speed) and kept it labelled experimental.

**Then what is the product?** The air-mixing signal: it's backed by held-out data for Delhi and Gurugram, it's cheap, and it comes from a public weather feed. Smoke is the context layered on top.

**How good is the evidence?** Three seasons, one data source, Delhi and Gurugram only, tested on reanalysis weather. The hourly snapshots the system now saves let us re-test on real forecasts. We state this in the README.

**Why not just use AQI?** AQI describes the present. We predict whether mixing will be poor over the next 48 hours, which is when a school can still change its plan.

**Is the advisory medical advice?** No, and it says so. The wording needs review against official CPCB/GRAP and school-health guidance before real-world use.

**Where does the data come from?** NASA FIRMS (satellite fire detections), Open-Meteo (weather, reanalysis and a CAMS air-quality baseline), and CPCB measurements via a public Kaggle dataset for validation.

**Why isn't the AI advisory live?** The Strands agent and its tools are built and tested, and it falls back to a template whenever the model can't be reached. Our new AWS account is still being unblocked for Bedrock.

**How do you know it's actually running?** The CloudWatch dashboard and five alarms: ingest errors, the ingest not running for two hours (missing data counts as failure), the ingest running but seeing zero fires three times in a row, API 5xx, and a failed run in the dead-letter queue. The ingest also emits custom metrics every hour.

**Has it ever broken in production?** Yes, and we found it ourselves: the fire request used a calendar-day window, so for about ten hours after midnight UTC (05:30-15:30 IST) the smoke estimate saw zero fires. Nothing errored; we spotted it in the saved hourly snapshots. We fixed it to an exact 24-hour window, added an alarm for "ran but saw nothing", and made the back-test skip empty snapshots. The air-mixing signal comes from weather data and was never affected.

**What did it cost?** Pennies a month on AWS for the pipeline; the only meaningful cost is Bedrock, which is capped by caching to 10 generations an hour (5 cities x 2 languages).

**What would you do with another month?** Score real forecasts, replace the smoke routing with a regional fire index, add measured PM2.5 for more cities, and review the advisory text with school-health guidance.

## One-line fallbacks if you freeze
- "Air mixing is the signal we trust; smoke is context."
- "We tested it on held-out seasons and told you where it fails."
- "The code that fixes the weak part is already collecting the data it needs."
