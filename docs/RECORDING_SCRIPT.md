# SmokeShield: demo video recording script

For the teammate recording the demo. You do not need to know the code. You need to read the narration clearly and click where the script says.
**Target length: about 4 minutes** (the narration is about 520 words, plus time for clicks and pauses). Check the hackathon's maximum length before you start. If it is shorter, see "If you need it shorter" near the end.

The judges score four things. Each scene is built to hit one of them. **"Built on AWS" is mandatory to win and is judged on how well AWS is used, so Scene 5 is the longest scene on purpose.**

| Scene | Judging criterion it earns |
|---|---|
| 1-3 (problem, live site, a bad day) | **Idea and impact**, and **Design and usability** |
| 4 (does it work?) | **Execution**: "does it work?" |
| 5 (AWS, three shots) | **Built on AWS** |

---

## 1. Read this first (60 seconds)

**What SmokeShield is.** A web page that tells a school in Delhi-NCR what to do about the air over the next two days: a plain one-line recommendation, a school day planner (assembly, PE, recess, classrooms, children with asthma, parents), and a message the school can send to parents, in English or Hindi. It runs entirely on AWS.

**What we are proud of, and what we are honest about.**
- **Air mixing** (will the air stay still and trap pollution?) was **tested on real data** for Delhi and Gurugram. It works.
- **Smoke arrival** (will crop-fire smoke reach us, and when?) is **experimental and did not validate**. We say so on the page. Saying it ourselves is a strength, so do not skip that part.
- The **AI-written advisory** is built but not live: our new AWS account is still waiting for access to Amazon Bedrock. Today the text comes from reviewed templates.

**Never say these** (they are not true, and judges may check):
- "It's safe" or "the air is safe." We say **OK / Limit / Avoid**, because we forecast conditions, we do not measure safety.
- "The smoke forecast works" or "predicts smoke accurately."
- "The AI writes the advice" (it will, once Bedrock is unblocked; right now it does not).
- "Validated for all cities." Only **Delhi and Gurugram** are validated.
- "Real schools use it." They do not yet.
- Any AWS service not on the list in section 7. We do **not** use Step Functions, Cognito, Cedar, Route 53, LocalStack or OpenSearch.

---

## 2. Set up (15 minutes before recording)

**Your screen**
- Use Chrome, one window, **100% zoom**, bookmarks bar hidden, light mode.
- Close every other tab and app. Turn on **Do Not Disturb** so no notifications pop up.
- Screen size 1920x1080 if possible (1280x720 is fine). Plug in the laptop.

**Open these tabs in this order** (everything is public: nobody needs to log in to AWS)
1. **Live site:** https://main.d1nrk1hn0hdamc.amplifyapp.com
2. **Sample scenario:** the same address with `?mock=1` on the end: https://main.d1nrk1hn0hdamc.amplifyapp.com/?mock=1
3. **README evidence section:** open `README.md` (on GitHub or VS Code preview), scrolled to "Does it work? What the data says".
4. **Architecture picture:** open the file `docs/assets/architecture.html` in Chrome and press **F11** for full screen.
5. **Live API:** https://3oxq6ij166.execute-api.us-east-1.amazonaws.com/risk/delhi (it shows raw data text; that is expected and is the point).
6. **CloudWatch graph:** open the image `docs/assets/aws-fire-detections.png` (drag it into a Chrome tab, or open it in your image viewer at full size).

*(The images in `docs/assets/` are real graphs exported from our AWS account. You do not need, and should not use, the AWS console on camera: it shows the account number.)*

**Check before you record**
- Tab 1 should say **"Live data"** at the top right and **"Updated ... ago"** under the city name. If it shows an error or an old time, tell Nakul to run the data refresh, then reload.
- Tab 2 should show a **"Sample"** pill in the top right, with Delhi selected on an **amber** card.
- Tab 5 should show text starting with `{"fires_total": ...`, and further along `"name": "Delhi"` and a recent `generated_at`. If it says "no data yet" or an error, tell Nakul.
- Click **हिं** and back to **EN** once, so you know where the button is.

**Recording tool:** Windows: **Win + Alt + R** (Xbox Game Bar) or OBS. Mac: Shift + Cmd + 5. Loom also works. **Test your microphone for 5 seconds and play it back.** Use a quiet room.

**Tip:** record each scene as its own clip. It is much easier to redo one scene than the whole video.

---

## 3. The recording, scene by scene

> Speak a little slower than normal and leave one second of silence at the start and end of each scene. Move the mouse slowly. Do not wiggle it.
> Lines marked **(optional)** add about 15 seconds each. Include them if you have time.

### Scene 1: the problem (0:00 - 0:20)
**Show:** Tab 1 (live site). Mouse still.
**Say:**
> "Every autumn, smoke from crop fires drifts toward Delhi. On bad days, schools must decide whether tomorrow's assembly, sports and buses are okay. Today's air-quality number tells them how bad the air *is*. SmokeShield tells them what to *do*, in plain English and Hindi."

### Scene 2: the live site (0:20 - 0:55)
**Show:** Tab 1. **Click Delhi** in the city row at the top. Point the mouse briefly at the address bar (it ends in `amplifyapp.com`).
**Say:**
> "This is our live site, hosted on AWS Amplify. Every hour, an AWS pipeline pulls NASA fire detections and weather forecasts for five cities."

**Point the mouse at the big coloured card.**
> "A school sees one sentence first: today's recommendation."
> *(optional)* "Today is a quiet day, so it says no smoke precautions are needed, and that is the honest answer."

**Point at the School day planner card, then the Air mixing meter.**
> "Under it, a school day planner, and air mixing: how well the air will disperse pollution over the next two days."

**Click the हिं button at the top right, wait two seconds, then click EN.**
> "One tap, and it is all in Hindi."

*(If the live site shows "Limit" or "Avoid" on the day you record, read what is on screen instead. Never read a sentence that does not match the screen.)*

### Scene 3: a bad day (0:55 - 1:45)
**Show:** Switch to Tab 2 (the sample scenario). Delhi is selected.
**Say:**
> "Here is a bad day: a labelled sample scenario with made-up weather. Smoke is estimated in about six hours and air mixing is poor, so the card turns amber: move strenuous sport indoors, and prefer midday for outdoor activity."

**Point at the "Sample" pill, then the amber card. Scroll slowly through the planner rows.**
> "The planner covers every school activity, from assembly to children with asthma."

**Click "Copy notice". Wait for the button to turn green and say "Copied".**
> "And for the principal's busiest job, a ready-to-send notice for parents, in English or Hindi."

**Click हिं once so the notice shows in Hindi, then back to EN.**

### Scene 4: does it work? (1:45 - 2:25)
**Show:** Tab 3: the README evidence tables ("Does it work? What the data says").
**Say:**
> "We tested it on three real seasons of measured air quality. Air mixing works: in Delhi and Gurugram, days we labelled poor averaged 249 micrograms of fine particles, moderate 192, good 175, and the order held on seasons we held back."

**Point at the "Smoke arrival: not shown to work" paragraph.**
> "The smoke forecast did not hold up. So we label it experimental on the page, and we are fixing the method, not the claim."

### Scene 5: built on AWS (2:25 - 4:00): three shots

**This is the scene judges weigh most for AWS. Take your time and keep each picture on screen while you talk about it.**

**Shot 5a: how it is built (about 45 seconds). Show Tab 4, the architecture picture, full screen.**
**Say:**
> "Here is how it runs on AWS. An EventBridge schedule triggers a Lambda function every hour. It pulls NASA's fire detections and weather, scores five cities, and writes the result to DynamoDB, with raw snapshots in S3 so we can test the model later. Failed runs are kept in an SQS queue, and high-smoke alerts go out through SNS. Visitors reach the data through API Gateway and two more Lambdas, and the map is hosted on Amplify. The whole thing is one SAM template, deployed with two commands in about three minutes."

*(While you say each service, move the mouse slowly to its box: EventBridge, Lambda ingest, DynamoDB, S3, SQS, SNS, API Gateway, Amplify.)*

**Shot 5b: proof it is real (about 20 seconds). Show Tab 5, the live API text.**
**Say:**
> "And it is real. This is our live API on API Gateway, returning today's record for Delhi straight from DynamoDB."

**Shot 5c: how we run it (about 30 seconds). Show Tab 6, the fire-detections graph.**
**Say:**
> "This is CloudWatch. Every run reports how many fires it saw. See the flat line, then a drop to zero: a bug where our time window hid the morning's fires. We found it, fixed it, and added an alarm for it. Five alarms now watch the pipeline, including one for 'the job ran but saw nothing'."

**Back to Tab 4 (architecture), then say:**
> "The advisory is designed to be written by a Strands agent on Amazon Bedrock, with three tools and a template fallback. That code is built and tested, but our new AWS account is still waiting for Bedrock access, so today the advice comes from reviewed templates. Running costs are pennies a month, and caching limits Bedrock to ten calls an hour."
> *(optional)* "There are 185 automated tests."

### Scene 6: close (4:00 - 4:15)
**Show:** Tab 1 (live site), mouse still.
**Say:**
> "SmokeShield: one signal tested on real data, one honestly labelled experimental, a pipeline already collecting data to improve it, and all of it running on AWS. Thank you."

---

## 4. If you need it shorter
- **Under 3 minutes 30:** drop every **(optional)** line, and skip **Shot 5b** (the live API).
- **Under 3 minutes:** also trim Shot 5a to one sentence: "An EventBridge schedule runs a Lambda every hour; DynamoDB and S3 store the data, API Gateway and Amplify serve it, and CloudWatch watches it." Keep Shot 5c and the Strands/Bedrock sentences, because those carry the AWS score.
- **Under 2 minutes:** do Scenes 1, 3, 4 and 6 only, plus this one sentence from Scene 5: "It runs entirely on AWS, from EventBridge and Lambda to DynamoDB, API Gateway, Amplify and CloudWatch, with a Strands agent on Bedrock designed to write the advice."

## 5. If something goes wrong

| Problem | What to do |
|---|---|
| Live site shows an error or is blank | Stop. Tell Nakul (the data refresh may need running). Use the sample scenario for Scenes 2 and 3 and say "this is the same page on sample data." |
| Live site shows a different status than the script says | Read what is on screen. Do not read the script's wording if it does not match. |
| The live API tab shows an error or "no data yet" | Tell Nakul. Skip Shot 5b. |
| The map looks grey or empty | Wait 5 seconds for tiles to load, or zoom the map in once. |
| "Copy notice" does not turn green | Click it again once. If it still fails, say "one tap to copy" and move on. |
| You stumble | Pause, take a breath, and restart the sentence from the beginning. You can cut it out later. |
| Someone suggests recording the AWS console | Do not. It shows the account number. Use the images in `docs/assets/`. |

## 6. Before you export
- Watch the whole video once. Check that **no browser tabs, notifications, passwords or the AWS account number** are visible.
- Export as **MP4, 1080p**. Name it `SmokeShield-demo.mp4`.
- Check the hackathon's required length and file size, and send the file to Nakul.

## 7. Cheat sheet: how we used AWS (say only these)

| AWS service | What we use it for |
|---|---|
| **EventBridge** | Hourly schedule that starts the pipeline |
| **Lambda** (3 functions + shared layer) | `ingest` (fires + weather, scoring), `api` (reads records), `advisory` (writes the advice) |
| **DynamoDB** | One risk record per city per hour (pay-per-request) |
| **S3** | Raw hourly snapshots, kept to test the model later |
| **API Gateway** (HTTP API) | The public API the website calls; origins locked to our site |
| **Amplify Hosting** | The static website |
| **SNS** | Alerts when smoke risk is high, and alarm notifications |
| **SQS** | Dead-letter queue that keeps any failed hourly run for 14 days |
| **CloudWatch** | 7 custom metrics, a dashboard, **5 alarms**, 30-day log retention |
| **SAM / CloudFormation** | One `template.yaml` defines everything; `sam build` + `sam deploy` |
| **Strands Agents SDK + Amazon Bedrock** | Built and tested (3 tools, template fallback). **Not live yet:** our new account is waiting for Bedrock access |

**Other numbers:** Cities: Delhi, Gurugram, Chandigarh, Ludhiana, Jaipur (**validated:** Delhi and Gurugram only). Air-mixing results on held-out seasons: poor 249, moderate 192, good 175 micrograms per cubic metre; days at or above 150: 94%, 76%, 59%. Smoke forecast: experimental. Tests: 185. Languages: English and Hindi.
