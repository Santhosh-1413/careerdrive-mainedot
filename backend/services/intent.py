"""
Intent Classifier + Parameter Extractor
USA-only location extraction · transport role detection · salary/experience capture
"""

import re
import logging
from dataclasses import dataclass, field

log = logging.getLogger("transitbot.intent")

INTENTS = {
    "job_search":    "find jobs search openings hiring employment opportunities",
    "career_advice": "career path roadmap progression growth plan advice transition",
    "skill_gap":     "skills certifications training courses what do I need to learn",
    "salary_info":   "salary pay compensation how much does it pay wage",
    "resume_help":   "resume CV profile improve review feedback",
    "networking":    "networking events conferences connections associations",
    "career_map":    "career map show paths visualization roles graph",
    "onet_lookup":   "job description duties tasks responsibilities typical day",
    "general":       "hello hi thanks greeting how are you",
}

INTENT_MODULE = {
    "job_search":"job_finder","onet_lookup":"job_finder",
    "career_advice":"career_chat","skill_gap":"career_chat",
    "salary_info":"career_chat","resume_help":"career_chat","networking":"career_chat",
    "career_map":"career_map","general":"general",
}

US_STATES = {
    "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA",
    "colorado":"CO","connecticut":"CT","delaware":"DE","florida":"FL","georgia":"GA",
    "hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS",
    "kentucky":"KY","louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA",
    "michigan":"MI","minnesota":"MN","mississippi":"MS","missouri":"MO","montana":"MT",
    "nebraska":"NE","nevada":"NV","new hampshire":"NH","new jersey":"NJ","new mexico":"NM",
    "new york":"NY","north carolina":"NC","north dakota":"ND","ohio":"OH","oklahoma":"OK",
    "oregon":"OR","pennsylvania":"PA","rhode island":"RI","south carolina":"SC",
    "south dakota":"SD","tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT",
    "virginia":"VA","washington":"WA","west virginia":"WV","wisconsin":"WI","wyoming":"WY",
    "district of columbia":"DC","al":"AL","ak":"AK","az":"AZ","ar":"AR","ca":"CA",
    "co":"CO","ct":"CT","de":"DE","fl":"FL","ga":"GA","hi":"HI","id":"ID","il":"IL",
    "in":"IN","ia":"IA","ks":"KS","ky":"KY","la":"LA","me":"ME","md":"MD","ma":"MA",
    "mi":"MI","mn":"MN","ms":"MS","mo":"MO","mt":"MT","ne":"NE","nv":"NV","nh":"NH",
    "nj":"NJ","nm":"NM","ny":"NY","nc":"NC","nd":"ND","oh":"OH","ok":"OK","or":"OR",
    "pa":"PA","ri":"RI","sc":"SC","sd":"SD","tn":"TN","tx":"TX","ut":"UT","vt":"VT",
    "va":"VA","wa":"WA","wv":"WV","wi":"WI","wy":"WY","dc":"DC",
}

SECTOR_MAP = [
    (r"\b(rail|railroad|metro|subway|light rail|commuter rail|amtrak|FRA)\b","railways","Rail & transit"),
    (r"\b(highway|road|bridge|freeway|interstate|FHWA|pavement|DOT)\b","highways","Highways & roads"),
    (r"\b(aviation|airport|airline|FAA|air traffic|aircraft|airfield|ATC)\b","aviation","Aviation"),
    (r"\b(port|maritime|shipping|harbor|vessel|marine|MARAD|waterway)\b","maritime","Ports & maritime"),
    (r"\b(EV|electric vehicle|autonomous|connected vehicle|smart mobility|MaaS|V2X)\b","urban_planning","Smart mobility"),
    (r"\b(transit|bus|BRT|public transport|FTA|ridership|GTFS|paratransit)\b","public_transit","Public transportation"),
    (r"\b(logistics|supply chain|freight|cargo|warehouse|distribution|intermodal)\b","logistics","Logistics"),
    (r"\b(urban planning|city planning|land use|zoning|MPO|comprehensive plan)\b","urban_planning","Urban planning"),
]

_ROLE_RE = re.compile(
    r"\b((?:senior|junior|lead|principal|staff|associate|assistant)?\s*"
    r"(?:civil|structural|mechanical|electrical|systems|transportation|traffic|highway|"
    r"rail|railroad|transit|aviation|maritime|port|logistics|supply chain|urban|"
    r"environmental|GIS|geospatial|data|software|smart mobility|autonomous|ITS)\s*"
    r"(?:engineer|manager|analyst|planner|specialist|coordinator|technician|"
    r"inspector|director|officer|supervisor|designer|architect|scientist|consultant|developer))\b",
    re.I
)

_ROLE_EXACT = re.compile(
    r"\b(air traffic controller|locomotive engineer|railroad conductor|subway operator|"
    r"streetcar operator|ship captain|marine pilot|ship engineer|bridge tender|"
    r"airfield operations specialist|transportation inspector|traffic technician|"
    r"logistician|cartographer|urban planner|transit planner|transportation planner|"
    r"project manager|program manager|data scientist|data engineer|data analyst|"
    r"logistics manager|supply chain manager|logistics analyst)\b",
    re.I
)

_ROLE_FALLBACK = re.compile(
    r"\b([a-z]+(?:\s+[a-z]+)?\s+(?:inspector|engineer|analyst|manager|coordinator|"
    r"planner|specialist|technician|operator|supervisor|director|controller|pilot|"
    r"conductor|dispatcher|consultant|advisor|developer|architect))\b",
    re.I
)

_NON_US = re.compile(
    r"\b(uk|united kingdom|canada|australia|india|europe|germany|france|"
    r"london|toronto|sydney|paris|berlin|delhi|mumbai|dubai|singapore)\b", re.I
)

_JOB_KW  = re.compile(r"\b(job|jobs|role|roles|position|positions|opening|openings|vacancy|vacancies|hiring|find|search|available|opportunities|opportunity|listing|listings)\b", re.I)
_JOB_STRONG = re.compile(r"(looking for|searching for|find me|show me|get me|give me|any|find|search).{0,30}(job|jobs|position|positions|role|roles|work|opening|openings|listing|listings|vacancy|vacancies)", re.I)
_CARE_KW = re.compile(r"\b(career|grow|progress|advance|roadmap|plan|certif|skill|learn|course|salary|pay|network|resume|cv|improve|develop|transition|switch)\b", re.I)
_MAP_KW  = re.compile(r"\b(map|graph|visual|career map|paths from|show paths)\b", re.I)
_ONET_KW = re.compile(r"\b(what does|what do|describe|duties|responsibilities|tasks|day.to.day|typical day|job description)\b", re.I)
_SAL_KW  = re.compile(r"\b(salary|pay|wage|earn|compensat|how much|income)\b", re.I)
_SKL_KW  = re.compile(r"\b(skill|certif|qualif|learn|course|training|license|need to know)\b", re.I)


@dataclass
class ExtractedParams:
    role: str = ""
    sector: str = ""
    domain: str = ""
    location: str = ""
    state_code: str = ""
    experience: str = ""
    experience_years: int = 0
    salary_min: int = 0
    salary_max: int = 0
    schedule: str = ""
    keywords: str = ""
    non_us_mentioned: bool = False


def extract_params(text: str) -> ExtractedParams:
    p = ExtractedParams()
    tl = text.lower()

    # Role
    for pat in [_ROLE_EXACT, _ROLE_RE]:
        m = pat.search(text)
        if m: p.role = m.group(1).strip(); break
    if not p.role:
        m = _ROLE_FALLBACK.search(tl)
        if m:
            role_raw = m.group(1).strip()
            # Strip schedule words that got pulled into the role name
            for word in ("remote", "hybrid", "onsite", "on-site", "local", "senior", "junior"):
                role_raw = re.sub(r"^" + word + r"\s+", "", role_raw, flags=re.I)
            p.role = role_raw.strip()
            p.keywords = p.role

    # Sector
    for pattern, domain, label in SECTOR_MAP:
        if re.search(pattern, text, re.I):
            p.domain = domain; p.sector = label; break

    # Non-US check
    if _NON_US.search(tl): p.non_us_mentioned = True

    # US location
    loc_m = re.search(r"\bin\s+([A-Z][a-zA-Z\s]{2,25}?)(?:\s*,\s*[A-Z]{2})?\b", text)
    if loc_m:
        raw = loc_m.group(1).strip()
        rl = raw.lower()
        if rl in US_STATES:
            p.state_code = US_STATES[rl]; p.location = raw
        elif not _NON_US.search(raw):
            p.location = raw

    if not p.location:
        for name, code in US_STATES.items():
            if len(name) > 2 and re.search(r'\b' + re.escape(name) + r'\b', tl):
                p.state_code = code; p.location = name.title(); break

    if not p.location and re.search(r'\b(remote|anywhere|nationwide)\b', tl, re.I):
        p.location = "remote"; p.schedule = "remote"

    # Experience
    for pat, kind in [
        (r"(\d+)\s*[-to]+\s*(\d+)\s*years?","range"),
        (r"(\d+)\+\s*years?","min"),
        (r"(\d+)\s*years?\s*(?:of\s*)?(?:experience|exp)","exact"),
        (r"\b(entry.level|entry level|new grad|fresh)\b","entry"),
        (r"\b(mid.level|mid level|intermediate)\b","mid"),
        (r"\b(senior|lead|principal|staff)\b","senior"),
    ]:
        m = re.search(pat, tl, re.I)
        if m:
            if kind == "range": p.experience = f"{m.group(1)}-{m.group(2)} years"; p.experience_years = (int(m.group(1))+int(m.group(2)))//2
            elif kind == "min": p.experience = f"{m.group(1)}+ years"; p.experience_years = int(m.group(1))
            elif kind == "exact": p.experience = f"{m.group(1)} years"; p.experience_years = int(m.group(1))
            else: p.experience = kind
            break

    # Salary
    for pat, kind in [
        (r"\$(\d{2,3})[kK]\s*[-to]+\s*\$?(\d{2,3})[kK]","range"),
        (r"\$(\d{2,3})[kK]","single"),
    ]:
        m = re.search(pat, tl, re.I)
        if m:
            if kind == "range": p.salary_min = int(m.group(1))*1000; p.salary_max = int(m.group(2))*1000
            else: p.salary_min = int(m.group(1))*1000
            break

    # Schedule
    for sched, pat in [
        ("remote", r"\b(remote|WFH|fully remote)\b"),
        ("hybrid", r"\b(hybrid|partially remote)\b"),
        ("onsite", r"\b(on.?site|in.?office)\b"),
    ]:
        if re.search(pat, tl, re.I):
            p.schedule = sched
            if sched == "remote" and not p.location: p.location = "remote"
            break

    if not p.keywords and p.role: p.keywords = p.role
    return p


@dataclass
class IntentResult:
    intent: str
    confidence: float
    module: str
    params: dict = field(default_factory=dict)
    extracted: ExtractedParams = field(default_factory=ExtractedParams)


_classifier = None
_TRANSFORMERS_AVAILABLE = False

def _load_classifier():
    global _classifier, _TRANSFORMERS_AVAILABLE
    if _classifier is not None: return _classifier
    try:
        from transformers import pipeline
        _classifier = pipeline("zero-shot-classification",
                               model="typeform/distilbert-base-uncased-mnli", device=-1)
        _TRANSFORMERS_AVAILABLE = True
        log.info("DistilBERT classifier loaded")
    except Exception as e:
        log.info("DistilBERT not available (%s) — using keyword fallback", e)
    return _classifier


def _kw_classify(text: str) -> str:
    tl = text.lower()
    if "career map" in tl: return "career_map"
    if _ONET_KW.search(tl): return "onet_lookup"
    if _SAL_KW.search(tl): return "salary_info"
    if _SKL_KW.search(tl): return "skill_gap"
    j = len(_JOB_KW.findall(tl))
    c = len(_CARE_KW.findall(tl))
    # Strong job search phrases override score comparison
    if _JOB_STRONG.search(tl): return "job_search"
    if j > 0 and j >= c: return "job_search"
    if c > 0: return "career_advice"
    if _MAP_KW.search(tl): return "career_map"
    return "general"


def classify(text: str) -> IntentResult:
    extracted = extract_params(text)
    clf = _load_classifier()
    intent = "general"
    confidence = 0.7

    if clf:
        try:
            result = clf(text, list(INTENTS.values()), multi_label=False)
            top = result["labels"][0]
            intent = next((k for k, v in INTENTS.items() if v == top), "general")
            confidence = result["scores"][0]
        except Exception as e:
            log.warning("Classifier error: %s", e)
            intent = _kw_classify(text)
    else:
        intent = _kw_classify(text)

    if intent == "general" and extracted.role and (extracted.location or extracted.sector or extracted.schedule):
        intent = "job_search"; confidence = 0.85
    # "looking for X positions/roles" is always job search
    if intent in ("general", "career_advice") and _JOB_STRONG.search(text.lower()):
        intent = "job_search"; confidence = 0.90

    module = INTENT_MODULE.get(intent, "general")

    params = {}
    if extracted.role:           params["role"] = extracted.role
    if extracted.location:       params["location"] = extracted.location
    if extracted.state_code:     params["state_code"] = extracted.state_code
    if extracted.sector:         params["sector"] = extracted.sector
    if extracted.domain:         params["domain"] = extracted.domain
    if extracted.keywords:       params["keywords"] = extracted.keywords
    if extracted.salary_min:     params["salary_min"] = extracted.salary_min
    if extracted.experience:     params["experience"] = extracted.experience
    if extracted.schedule:       params["schedule"] = extracted.schedule
    if extracted.non_us_mentioned: params["non_us_mentioned"] = True

    log.info("Intent=%s(%.2f) role='%s' loc='%s' domain='%s'",
             intent, confidence, extracted.role, extracted.location, extracted.domain)

    return IntentResult(intent=intent, confidence=confidence,
                        module=module, params=params, extracted=extracted)
