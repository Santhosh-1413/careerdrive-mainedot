"""US transportation job boards — Maine-specific and national."""

MAINE_BOARDS = [
    {"id":"mainedot","name":"MaineDOT Careers","url":"https://www.maine.gov/mdot/careers/",
     "focus":"Transportation engineers, highway crews, bridge operations","geo":"maine",
     "domains":["highways","railways","urban_planning"]},
    {"id":"maine_turnpike","name":"Maine Turnpike Authority","url":"https://www.maineturnpike.com/About-MTA/Careers.aspx",
     "focus":"Toll and highway systems, maintenance","geo":"maine","domains":["highways"]},
    {"id":"maine_gov","name":"Maine.gov Job Board","url":"https://www.maine.gov/jobs/",
     "focus":"State engineering and project management","geo":"maine","domains":["highways","urban_planning"]},
    {"id":"cianbro","name":"Cianbro Careers","url":"https://www.cianbro.com/careers",
     "focus":"Heavy civil, structural, electrical","geo":"maine","domains":["highways"]},
    {"id":"sebago_technics","name":"Sebago Technics","url":"https://www.sebagotechnics.com/careers",
     "focus":"Civil engineering and survey","geo":"maine","domains":["highways","urban_planning"]},
    {"id":"live_work_maine","name":"Live and Work in Maine","url":"https://www.liveandworkinmaine.com/jobs/",
     "focus":"Professional careers, relocation support","geo":"maine","domains":["all"]},
]

NATIONAL_BOARDS = [
    {"id":"usajobs","name":"USAJobs.gov","url":"https://www.usajobs.gov",
     "focus":"Federal transportation roles — FHWA, FTA, FRA, FAA, Army Corps","geo":"national",
     "domains":["all"]},
    {"id":"aashto","name":"AASHTO Jobs","url":"https://jobs.transportation.org",
     "focus":"State DOT and highway engineering roles","geo":"national","domains":["highways"]},
    {"id":"ite_hire","name":"ITE Hire","url":"https://jobs.ite.org",
     "focus":"Traffic engineering and smart mobility","geo":"national","domains":["highways","urban_planning"]},
    {"id":"asce_careers","name":"ASCE Career Connections","url":"https://careers.asce.org",
     "focus":"Civil and structural engineers","geo":"national","domains":["highways","railways"]},
    {"id":"engineer_jobs","name":"EngineerJobs.com","url":"https://www.engineerjobs.com",
     "focus":"All engineering disciplines","geo":"national","domains":["all"]},
    {"id":"construction_jobs","name":"ConstructionJobs.com","url":"https://www.constructionjobs.com",
     "focus":"Heavy civil and infrastructure construction","geo":"national","domains":["highways"]},
    {"id":"ihire","name":"iHireConstruction","url":"https://www.ihireconstruction.com",
     "focus":"Management and skilled trades","geo":"national","domains":["highways"]},
    {"id":"roadtechs","name":"RoadTechs","url":"https://www.roadtechs.com",
     "focus":"Heavy civil and energy infrastructure","geo":"national","domains":["highways","logistics"]},
    {"id":"michael_page","name":"Michael Page Construction","url":"https://www.michaelpage.com/jobs/construction",
     "focus":"Senior PMs and executives","geo":"national","domains":["all"]},
]

ALL_BOARDS = MAINE_BOARDS + NATIONAL_BOARDS


def get_boards(domain: str = "", location: str = "") -> list[dict]:
    """Return relevant boards for domain and location."""
    is_maine = "maine" in location.lower() if location else False
    scored = []
    for b in ALL_BOARDS:
        score = 0
        if is_maine and b["geo"] == "maine": score += 10
        elif not is_maine and b["geo"] == "national": score += 5
        if "all" in b["domains"] or domain in b["domains"]: score += 3
        if score > 0: scored.append((score, b))
    scored.sort(key=lambda x: -x[0])
    return [b for _, b in scored[:6]]


def format_boards_for_prompt(domain: str, location: str) -> str:
    boards = get_boards(domain, location)
    if not boards: return ""
    lines = ["Recommended job boards for this role:"]
    for b in boards:
        geo = "Maine" if b["geo"] == "maine" else "National"
        lines.append(f"  • {b['name']} ({geo}) — {b['focus']} → {b['url']}")
    return "\n".join(lines)
