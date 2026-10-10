"""Canned school guidance, in English and Hindi.

The agent must NOT invent health advice: it explains the numbers and chooses from these tables. The same tables drive the
template advisory (used whenever the agent is unavailable) and the one-line recommendation shown at the top of the map.

TODO before the demo: have the English wording checked against official CPCB/GRAP and state education-department guidance,
and have the Hindi wording read by a Hindi speaker. Cite the sources in the README.
"""

LANGS = ("en", "hi")

# ---- smoke guidance (English; the agent tools read these) ------------------------------------------------------------
GUIDANCE = {
    "LOW": {
        "headline": "No significant crop-fire smoke expected",
        "short": "No smoke precautions needed.",
        "actions": ["Normal outdoor activities", "Keep monitoring the daily forecast"],
    },
    "MODERATE": {
        "headline": "Some smoke may reach the city",
        "short": "Move strenuous sport and long assemblies indoors while smoke is expected.",
        "actions": [
            "Move strenuous outdoor sports and long assemblies indoors during the arrival window",
            "Allow students with asthma to stay indoors and keep their inhalers at hand",
        ],
    },
    "HIGH": {
        "headline": "Heavy smoke likely",
        "short": "Cancel outdoor PE, sport and assemblies while smoke is expected, and warn parents early.",
        "actions": [
            "Cancel outdoor PE, sports and assemblies during the arrival window",
            "Keep windows and doors shut while smoke is present; avoid sweeping or burning anything on campus",
            "Tell parents in advance; let vulnerable students (asthma, heart or lung conditions) stay home",
        ],
    },
    "SEVERE": {
        "headline": "Severe smoke episode likely",
        "short": "Keep all activity indoors and consider online classes for the worst hours.",
        "actions": [
            "Hold all activity indoors; consider shifting classes online or closing for the worst hours",
            "Alert parents now and publish the plan before the arrival window starts",
            "Allow vulnerable students and staff to stay home without penalty",
        ],
    },
}

GUIDANCE_HI = {
    "LOW": {
        "headline": "पराली के धुएँ का कोई उल्लेखनीय असर अपेक्षित नहीं",
        "short": "धुएँ के लिए किसी विशेष सावधानी की ज़रूरत नहीं।",
        "actions": ["बाहरी गतिविधियाँ सामान्य रूप से जारी रखें", "रोज़ का पूर्वानुमान देखते रहें"],
    },
    "MODERATE": {
        "headline": "शहर तक कुछ धुआँ पहुँच सकता है",
        "short": "धुआँ आने के समय ज़ोरदार खेल-कूद और लंबी सभाएँ भीतर करें।",
        "actions": [
            "धुआँ पहुँचने के समय ज़ोरदार बाहरी खेल और लंबी सभाएँ भीतर करें",
            "दमा वाले विद्यार्थियों को भीतर रहने दें और उनका इन्हेलर पास रखें",
        ],
    },
    "HIGH": {
        "headline": "भारी धुआँ आने की संभावना",
        "short": "धुआँ आने के समय बाहर पीटी, खेल और सभाएँ रद्द करें और अभिभावकों को पहले से बताएँ।",
        "actions": [
            "धुआँ पहुँचने के समय बाहर पीटी, खेल और सभाएँ रद्द करें",
            "धुआँ रहने तक खिड़की-दरवाज़े बंद रखें; परिसर में झाड़ू लगाने या कुछ भी जलाने से बचें",
            "अभिभावकों को पहले से सूचित करें; कमज़ोर विद्यार्थियों (दमा, हृदय या फेफड़ों की बीमारी) को घर पर रहने दें",
        ],
    },
    "SEVERE": {
        "headline": "गंभीर धुएँ की स्थिति की संभावना",
        "short": "सारी गतिविधियाँ भीतर रखें और सबसे खराब घंटों के लिए ऑनलाइन कक्षाओं पर विचार करें।",
        "actions": [
            "सारी गतिविधियाँ भीतर रखें; सबसे खराब घंटों के लिए कक्षाएँ ऑनलाइन करने या स्कूल बंद करने पर विचार करें",
            "अभिभावकों को अभी सूचित करें और धुआँ पहुँचने से पहले योजना बता दें",
            "कमज़ोर विद्यार्थियों और स्टाफ़ को बिना किसी दंड के घर पर रहने दें",
        ],
    },
}

LEVEL_NAMES_HI = {"LOW": "कम", "MODERATE": "मध्यम", "HIGH": "उच्च", "SEVERE": "गंभीर"}


def guidance_for(level, lang="en"):
    table = GUIDANCE_HI if lang == "hi" else GUIDANCE
    return table.get(level, table["LOW"])


# ---- air-mixing (stagnation) guidance --------------------------------------------------------------------------------
# Only POOR carries advice; the evidence base is documented in model.py and the README.
STAGNATION_GUIDANCE = {
    "POOR": {
        "headline": "Air is expected to mix poorly over the next 48 hours",
        "short": "Air is expected to mix poorly: prefer midday or afternoon for outdoor activity.",
        "note": ("Low boundary layer and weak winds let pollution from all sources, smoke included, build up near the ground, "
                 "mostly at night and in the morning."),
        "actions": ["Prefer midday or afternoon for outdoor activity over early morning and evening"],
    },
}

STAGNATION_GUIDANCE_HI = {
    "POOR": {
        "headline": "अगले 48 घंटों में हवा का मिश्रण कमज़ोर रहने की संभावना है",
        "short": "हवा का मिश्रण कमज़ोर रहने की संभावना है: बाहरी गतिविधियाँ सुबह-शाम की बजाय दोपहर में रखें।",
        "note": ("कम सीमा-परत और धीमी हवा के कारण सभी स्रोतों का प्रदूषण, धुआँ भी, ज़मीन के पास जमा हो जाता है, "
                 "ख़ासकर रात और सुबह में।"),
        "actions": ["बाहरी गतिविधियाँ सुबह जल्दी और शाम की बजाय दोपहर में रखना बेहतर है"],
    },
}


def stagnation_guidance(label, lang="en"):
    """Guidance for a stagnation label, or None when there is nothing to add (MODERATE, GOOD, unknown)."""
    return (STAGNATION_GUIDANCE_HI if lang == "hi" else STAGNATION_GUIDANCE).get(label)


def stagnation_applies(risk):
    """The label is only presented as advice for cities where it was checked against measured PM2.5."""
    return bool(risk.get("stagnation_validated")) and risk.get("stagnation") in STAGNATION_GUIDANCE


# ---- the one-line recommendation shown at the top of the map ----------------------------------------------------------
def recommendation(risk):
    """-> {'en': str, 'hi': str, 'tone': 'ok'|'caution'|'alert'}. Built from the same tables as the advisory."""
    level = risk.get("risk_level", "LOW")
    tone = {"LOW": "ok", "MODERATE": "caution", "HIGH": "alert", "SEVERE": "alert"}.get(level, "ok")
    parts = {"en": [guidance_for(level, "en")["short"]], "hi": [guidance_for(level, "hi")["short"]]}
    if stagnation_applies(risk):
        for lang in LANGS:
            parts[lang].append(stagnation_guidance(risk["stagnation"], lang)["short"])
        if tone == "ok":
            tone = "caution"
    return {"en": " ".join(parts["en"]), "hi": " ".join(parts["hi"]), "tone": tone}


# ---- school day planner ------------------------------------------------------------------------------------------------
# What a school can do about each activity, from the same two signals as everything else: the smoke estimate (experimental) and,
# for validated cities, poor air mixing. Statuses are deliberately OK / LIMIT / AVOID, never "safe": we forecast conditions, we do
# not measure safety. Same TODO as above: have the wording checked against official CPCB/GRAP and state guidance, and the Hindi read by a native speaker.
STATUS_WORDS = {"en": {"ok": "OK", "limit": "Limit", "avoid": "Avoid"}, "hi": {"ok": "ठीक", "limit": "सीमित", "avoid": "टालें"}}
KIDS_HEADLINE = {"en": "Outdoor activity for children: {}", "hi": "बच्चों की बाहरी गतिविधि: {}"}
_STATUS_BY_SEVERITY = ("ok", "limit", "avoid")
_SMOKE_SEVERITY = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 2}

# activity -> status -> (English, Hindi)
ACTIVITY_TEXT = {
    "assembly": {
        "ok": ("Fine to hold outdoors.", "बाहर आयोजित करना ठीक है।"),
        "limit": ("Keep it short or hold it indoors while smoke or stagnant air is expected.",
                  "छोटा रखें या भीतर करें, जब तक धुआँ या ठहरी हवा की संभावना है।"),
        "avoid": ("Hold it indoors.", "भीतर आयोजित करें।"),
    },
    "pe": {
        "ok": ("Normal sport and PE.", "सामान्य खेल और पीटी।"),
        "limit": ("Keep it light, or move strenuous sport indoors. Midday to afternoon is better than early morning or evening.",
                  "हल्की गतिविधि रखें या ज़ोरदार खेल भीतर करें। सुबह जल्दी या शाम की बजाय दोपहर बेहतर है।"),
        "avoid": ("Cancel outdoor PE and sport.", "बाहर पीटी और खेल रद्द करें।"),
    },
    "recess": {
        "ok": ("Normal breaks.", "सामान्य अंतराल।"),
        "limit": ("Keep breaks short and offer an indoor option.", "अंतराल छोटे रखें और भीतर का विकल्प दें।"),
        "avoid": ("Hold breaks indoors.", "अंतराल भीतर कराएँ।"),
    },
    "classroom": {
        "ok": ("Normal.", "सामान्य।"),
        "limit": ("Keep windows and doors shut while smoke is present; avoid sweeping or burning anything on campus.",
                  "धुआँ रहने तक खिड़की-दरवाज़े बंद रखें; परिसर में झाड़ू लगाने या कुछ भी जलाने से बचें।"),
    },
    "vulnerable": {
        "ok": ("Usual care; keep any inhalers or medicines at hand.", "सामान्य देखभाल; इन्हेलर या दवाइयाँ पास रखें।"),
        "limit": ("Let children with asthma stay indoors and keep inhalers at hand.", "दमा वाले बच्चों को भीतर रहने दें और इन्हेलर पास रखें।"),
        "avoid": ("Let children with asthma, heart or lung conditions stay home without penalty.",
                  "दमा, हृदय या फेफड़ों की बीमारी वाले बच्चों को बिना किसी दंड के घर पर रहने दें।"),
    },
    "parents": {
        "ok": ("No notice needed.", "सूचना की ज़रूरत नहीं।"),
        "limit": ("Tell parents if plans change.", "योजना बदले तो अभिभावकों को बताएँ।"),
        "avoid": ("Tell parents in advance and share the plan.", "अभिभावकों को पहले से बताएँ और योजना साझा करें।"),
    },
}
BEST_TIME = ("Best time for outdoor activity: midday to afternoon.", "बाहरी गतिविधि का बेहतर समय: दोपहर से अपराह्न तक।")


def _smoke_window(risk, lang):
    start, end, arrival = risk.get("window_start_hour"), risk.get("window_end_hour"), risk.get("arrival_hour")
    if arrival is None or start is None:
        return None
    if lang == "hi":
        return f"धुआँ लगभग {start} घंटे में अपेक्षित।" if start == end else f"धुआँ लगभग {start}-{end} घंटे में अपेक्षित।"
    return f"Smoke expected around {start} hours from now." if start == end else f"Smoke expected roughly {start}-{end} hours from now."


def _parent_notice(smoke_sev, mix_sev, lang):
    if smoke_sev == 2:
        return {
            "en": "Dear parents, the air forecast for the next two days shows heavy crop-fire smoke. We will cancel outdoor PE, sport and assemblies "
                  "while smoke is expected, and keep windows shut. Children with asthma, heart or lung conditions may stay home without penalty. "
                  "We will update you as the forecast changes.",
            "hi": "प्रिय अभिभावकगण, अगले दो दिनों के लिए हवा का पूर्वानुमान भारी पराली-धुएँ की संभावना दिखाता है। धुआँ आने के समय हम बाहर पीटी, "
                  "खेल और सभाएँ रद्द करेंगे और खिड़कियाँ बंद रखेंगे। दमा, हृदय या फेफड़ों की बीमारी वाले बच्चे बिना किसी दंड के घर पर रह सकते हैं। "
                  "पूर्वानुमान बदलने पर हम आपको सूचित करेंगे।"}[lang]
    if smoke_sev == 1 or mix_sev == 1:
        reasons = {"en": [], "hi": []}
        plans = {"en": [], "hi": []}
        if smoke_sev == 1:
            reasons["en"].append("that some crop-fire smoke may reach our city")
            reasons["hi"].append("शहर तक पराली का कुछ धुआँ पहुँच सकता है")
            plans["en"].append("keep strenuous sport and long assemblies indoors while smoke is expected")
            plans["hi"].append("धुआँ आने के समय ज़ोरदार खेल और लंबी सभाएँ भीतर करेंगे")
        if mix_sev == 1:
            reasons["en"].append("that air mixing may be poor, so pollution can build up near the ground")
            reasons["hi"].append("हवा का मिश्रण कमज़ोर रह सकता है, जिससे प्रदूषण ज़मीन के पास जमा हो सकता है")
            plans["en"].append("hold outdoor activity around midday to afternoon")
            plans["hi"].append("बाहरी गतिविधियाँ दोपहर के आसपास रखेंगे")
        if lang == "hi":
            return (f"प्रिय अभिभावकगण, अगले दो दिनों के लिए हवा का पूर्वानुमान दिखाता है: {' और '.join(reasons['hi'])}। हम {'; '.join(plans['hi'])}। "
                    "दमा वाले बच्चे भीतर रह सकते हैं और कृपया उनके इन्हेलर या दवाइयाँ सामान्य रूप से भेजें। पूर्वानुमान बदलने पर हम आपको बताएँगे।")
        return (f"Dear parents, the air forecast for the next two days shows {' and '.join(reasons['en'])}. We will {'; '.join(plans['en'])}. "
                "Children with asthma may stay indoors, and please send their inhalers or medicines as usual. We will update you if the forecast changes.")
    return {"en": "Dear parents, the air forecast for the next two days looks normal, so school activities will run as usual. We check the forecast daily.",
            "hi": "प्रिय अभिभावकगण, अगले दो दिनों के लिए हवा का पूर्वानुमान सामान्य है, इसलिए विद्यालय की गतिविधियाँ सामान्य रूप से चलेंगी। "
                  "हम रोज़ पूर्वानुमान देखते हैं।"}[lang]


def school_plan(risk):
    """-> {'status', 'headline', 'activities', 'best_time', 'smoke_window', 'notice'}, everything bilingual.

    status is the worse of the smoke estimate and (for validated cities) poor air mixing: OK, LIMIT or AVOID.
    """
    smoke_sev = _SMOKE_SEVERITY.get(risk.get("risk_level", "LOW"), 0)
    mix_sev = 1 if stagnation_applies(risk) else 0
    worst = max(smoke_sev, mix_sev)

    def st(severity):
        return _STATUS_BY_SEVERITY[severity]

    rows = [("assembly", st(worst)), ("pe", st(worst)), ("recess", st(smoke_sev)),
            ("classroom", "limit" if smoke_sev == 2 else "ok"),
            ("vulnerable", st(worst)), ("parents", st(worst))]
    activities = [{"id": a, "status": s, "text": {"en": ACTIVITY_TEXT[a][s][0], "hi": ACTIVITY_TEXT[a][s][1]}} for a, s in rows]
    status = st(worst)
    return {
        "status": status,
        "headline": {lang: KIDS_HEADLINE[lang].format(STATUS_WORDS[lang][status]) for lang in LANGS},
        "activities": activities,
        "best_time": {"en": BEST_TIME[0], "hi": BEST_TIME[1]} if mix_sev else None,
        "smoke_window": ({lang: _smoke_window(risk, lang) for lang in LANGS}
                         if smoke_sev >= 1 and _smoke_window(risk, "en") else None),   # one clean None, never {en: None, hi: None}
        "notice": {lang: _parent_notice(smoke_sev, mix_sev, lang) for lang in LANGS},
    }


# ---- template advisory (used whenever the Bedrock agent is unavailable) -----------------------------------------------
def fallback_advisory(city_name, risk, lang="en"):
    """Deterministic advisory in English or Hindi, assembled from the tables above."""
    return _fallback_hi(city_name, risk) if lang == "hi" else _fallback_en(city_name, risk)


def _fallback_en(city_name, risk):
    g = guidance_for(risk["risk_level"])
    lines = [f"{city_name}: {g['headline']} (risk {risk['risk_level']})."]
    if risk.get("arrival_hour") is not None:
        lead = "A small amount of smoke from" if risk["risk_level"] == "LOW" else "Smoke from"
        start, end = risk["window_start_hour"], risk["window_end_hour"]
        window = f"around {start} h" if start == end else f"between {start} h and {end} h"
        n_up = risk["fire_cells_upwind"]
        upwind = f"{n_up} of {risk['fire_cells_total']} active fire clusters {'is' if n_up == 1 else 'are'} upwind"
        lines.append(
            f"{lead} upwind crop fires is expected to start arriving in about {risk['arrival_hour']} h, "
            f"mostly {window} from now ({upwind})."
        )
    lines.append("Suggested actions:")
    lines += [f"- {a}" for a in g["actions"]]
    if stagnation_applies(risk):
        s = STAGNATION_GUIDANCE[risk["stagnation"]]
        lines += [f"Air mixing: {s['headline'].lower()}. {s['note']}"] + [f"- {a}" for a in s["actions"]]
    lines.append("This is a forecast estimate, not medical advice.")
    return "\n".join(lines)


def _fallback_hi(city_name, risk):
    level = risk["risk_level"]
    g = guidance_for(level, "hi")
    lines = [f"{city_name}: {g['headline']} (जोखिम: {LEVEL_NAMES_HI.get(level, level)})।"]
    if risk.get("arrival_hour") is not None:
        lead = "पराली जलने का थोड़ा-सा धुआँ" if level == "LOW" else "पराली जलने का धुआँ"
        start, end = risk["window_start_hour"], risk["window_end_hour"]
        window = f"ज़्यादातर लगभग {start} घंटे के आसपास" if start == end else f"ज़्यादातर अगले {start} से {end} घंटे के बीच"
        upwind = f"{risk['fire_cells_total']} में से {risk['fire_cells_upwind']} सक्रिय आग-समूह हवा के रुख़ में हैं"
        lines.append(f"{lead} लगभग {risk['arrival_hour']} घंटे में पहुँचना शुरू होने की संभावना है, {window} ({upwind})।")
    lines.append("सुझाई गई कार्रवाई:")
    lines += [f"- {a}" for a in g["actions"]]
    if stagnation_applies(risk):
        s = STAGNATION_GUIDANCE_HI[risk["stagnation"]]
        lines += [f"हवा का मिश्रण: {s['headline']}। {s['note']}"] + [f"- {a}" for a in s["actions"]]
    lines.append("यह पूर्वानुमान का अनुमान है, चिकित्सकीय सलाह नहीं।")
    return "\n".join(lines)
