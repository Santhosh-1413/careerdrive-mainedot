"""
O*NET Data Ingestion
=====================
Reads the five O*NET Excel files and loads all entities into Qdrant.
Runs once at startup if collections are empty.

Expected files in /app/data/onet/:
  Occupation_Data.xlsx
  Skills.xlsx
  Task_Statements.xlsx
  Technology_Skills.xlsx
  Education__Training__and_Experience_Categories.xlsx

Attribution: O*NET 29.0 Database, U.S. Department of Labor/ETA.
Licensed under Creative Commons Attribution 4.0 International.
"""

import os
import re
import logging
from pathlib import Path

log = logging.getLogger("transitbot.ingest")

# ── Transport SOC codes to include ────────────────────────────────────────────

TRANSPORT_CODES = [
    "17-2051.00","17-2051.01","17-2051.02",
    "19-3051.00","19-3099.01",
    "17-1021.00",
    "53-6041.00","53-6051.00","53-6051.01","53-6051.07",
    "53-4011.00","53-4031.00","53-4041.00","53-4099.00","53-4013.00",
    "53-2021.00","53-2022.00","53-2011.00",
    "53-5021.00","53-5031.00","53-6011.00",
    "11-3071.00","11-3071.04",
    "13-1081.00","13-1081.01","13-1081.02",
    "17-2199.00","17-2199.10","17-2199.11",
    "15-2041.00",
    "17-2071.00","17-2141.00",
]

DOMAIN_MAP = {
    "17-2051":"highways","19-3051":"urban_planning","19-3099":"urban_planning",
    "17-1021":"urban_planning","53-6041":"highways","53-6051":"railways",
    "53-6051.01":"aviation","53-4":"railways","53-2021":"aviation",
    "53-2022":"aviation","53-2011":"aviation","53-5":"maritime",
    "53-6011":"maritime","11-3071":"logistics","13-1081":"logistics",
    "17-2199":"urban_planning","15-2041":"urban_planning",
    "17-2071":"railways","17-2141":"railways",
}

SECTOR_LABELS = {
    "railways":"Rail & transit","highways":"Highways & roads",
    "aviation":"Aviation","maritime":"Ports & maritime",
    "logistics":"Logistics & supply chain","urban_planning":"Urban planning & smart mobility",
}

# BLS OES 2023 median wages
BLS_WAGES = {
    "17-2051.00":{"entry":"$67k","median":"$95k","senior":"$144k+"},
    "17-2051.01":{"entry":"$65k","median":"$93k","senior":"$140k+"},
    "17-2051.02":{"entry":"$60k","median":"$88k","senior":"$130k+"},
    "19-3051.00":{"entry":"$52k","median":"$79k","senior":"$115k+"},
    "19-3099.01":{"entry":"$54k","median":"$82k","senior":"$118k+"},
    "17-1021.00":{"entry":"$48k","median":"$72k","senior":"$105k+"},
    "53-6041.00":{"entry":"$38k","median":"$54k","senior":"$78k+"},
    "53-6051.00":{"entry":"$47k","median":"$79k","senior":"$112k+"},
    "53-6051.01":{"entry":"$52k","median":"$84k","senior":"$118k+"},
    "53-6051.07":{"entry":"$45k","median":"$74k","senior":"$105k+"},
    "53-4011.00":{"entry":"$58k","median":"$78k","senior":"$105k+"},
    "53-4031.00":{"entry":"$52k","median":"$71k","senior":"$98k+"},
    "53-4041.00":{"entry":"$48k","median":"$65k","senior":"$88k+"},
    "53-2021.00":{"entry":"$70k","median":"$137k","senior":"$184k+"},
    "53-2022.00":{"entry":"$42k","median":"$59k","senior":"$83k+"},
    "53-2011.00":{"entry":"$80k","median":"$171k","senior":"$239k+"},
    "53-5021.00":{"entry":"$62k","median":"$92k","senior":"$142k+"},
    "53-5031.00":{"entry":"$58k","median":"$85k","senior":"$122k+"},
    "11-3071.00":{"entry":"$62k","median":"$98k","senior":"$155k+"},
    "11-3071.04":{"entry":"$72k","median":"$115k","senior":"$170k+"},
    "13-1081.00":{"entry":"$55k","median":"$79k","senior":"$118k+"},
    "13-1081.01":{"entry":"$60k","median":"$90k","senior":"$130k+"},
    "13-1081.02":{"entry":"$52k","median":"$75k","senior":"$108k+"},
    "17-2199.00":{"entry":"$68k","median":"$104k","senior":"$155k+"},
    "15-2041.00":{"entry":"$58k","median":"$99k","senior":"$146k+"},
    "17-2071.00":{"entry":"$72k","median":"$106k","senior":"$155k+"},
    "17-2141.00":{"entry":"$65k","median":"$98k","senior":"$145k+"},
}

# Career path edges (from → to, difficulty 1-5, months min/max)
CAREER_PATHS = [
    ("17-1021.00","19-3099.01",2,6,12,"Lateral — GIS skills transfer directly to transit planning"),
    ("17-1021.00","15-2041.00",2,6,12,"Lateral — geospatial to data analytics"),
    ("17-1021.00","17-2051.01",3,12,24,"Upward — add Civil 3D and PE exam prep"),
    ("17-2051.01","17-2051.00",2,6,12,"Broadening — civil specialisation to general"),
    ("17-2051.01","19-3099.01",3,12,18,"Pivot — add planning coursework and AICP"),
    ("17-2051.00","53-6051.07",2,6,12,"Lateral — design to inspection"),
    ("19-3051.00","19-3099.01",1,3,6,"Specialisation — urban to transportation planning"),
    ("19-3099.01","17-2051.01",3,18,30,"Upward — add engineering degree or PE"),
    ("53-6051.07","53-4031.00",2,6,12,"Lateral — inspection to rail operations"),
    ("53-6041.00","17-2051.01",4,24,48,"Stretch — technician to engineer, needs degree"),
    ("53-4011.00","53-4031.00",2,6,12,"Lateral — operating to conducting"),
    ("53-4041.00","53-4031.00",2,6,12,"Upward — operator to conductor/yardmaster"),
    ("53-2022.00","53-2021.00",3,12,24,"Upward — operations to ATC, needs FAA cert"),
    ("11-3071.00","11-3071.04",2,6,18,"Specialisation — distribution to supply chain"),
    ("13-1081.02","13-1081.00",2,6,12,"Upward — analyst to logistician"),
    ("13-1081.01","11-3071.04",2,12,18,"Upward — logistics engineer to SC manager"),
    ("15-2041.00","17-2199.00",3,12,24,"Pivot — data to systems engineering, add CS skills"),
    ("17-2071.00","17-2199.00",2,6,12,"Lateral — electrical to general systems"),
    ("17-2141.00","17-2199.00",2,6,12,"Lateral — mechanical to systems engineering"),
]

# Curated certifications
CERTIFICATIONS = [
    {"id":"pe-license","name":"Professional Engineer (PE)","abbreviation":"PE",
     "org":"NCEES","cost_usd":500,"time_months":6,"education_req":"Bachelor's in engineering",
     "experience_req_years":4,"renewal_years":2,"exam_required":True,"is_free":False,
     "sector_ids":["highways","railways","aviation","maritime"],
     "description":"Required to stamp engineering designs. Gold standard for civil/transportation engineers."},
    {"id":"aicp","name":"American Institute of Certified Planners","abbreviation":"AICP",
     "org":"APA","cost_usd":395,"time_months":3,"education_req":"Bachelor's in planning or related",
     "experience_req_years":2,"renewal_years":2,"exam_required":True,"is_free":False,
     "sector_ids":["urban_planning","public_transit"],
     "description":"Primary credential for transportation and urban planners in the US."},
    {"id":"pmp","name":"Project Management Professional","abbreviation":"PMP",
     "org":"PMI","cost_usd":555,"time_months":3,"education_req":"Bachelor's degree",
     "experience_req_years":3,"renewal_years":3,"exam_required":True,"is_free":False,
     "sector_ids":["highways","railways","aviation","maritime","logistics","urban_planning"],
     "description":"Industry-standard PM credential, often required for infrastructure project managers."},
    {"id":"ptoe","name":"Professional Traffic Operations Engineer","abbreviation":"PTOE",
     "org":"ITE","cost_usd":350,"time_months":3,"education_req":"Bachelor's in engineering",
     "experience_req_years":5,"renewal_years":3,"exam_required":True,"is_free":False,
     "sector_ids":["highways","urban_planning"],
     "description":"Specialist credential for traffic engineering professionals."},
    {"id":"gisp","name":"GIS Professional Certification","abbreviation":"GISP",
     "org":"GISCI","cost_usd":250,"time_months":2,"education_req":"Bachelor's degree",
     "experience_req_years":4,"renewal_years":5,"exam_required":False,"is_free":False,
     "sector_ids":["urban_planning","highways"],
     "description":"Senior-level GIS credential demonstrating professional competency."},
    {"id":"cscp","name":"Certified Supply Chain Professional","abbreviation":"CSCP",
     "org":"APICS","cost_usd":1200,"time_months":4,"education_req":"Bachelor's degree",
     "experience_req_years":3,"renewal_years":3,"exam_required":True,"is_free":False,
     "sector_ids":["logistics","maritime"],
     "description":"Gold standard for supply chain management professionals."},
    {"id":"fhwa-nhi","name":"FHWA NHI Training Courses","abbreviation":"NHI",
     "org":"FHWA","cost_usd":0,"time_months":1,"education_req":"None",
     "experience_req_years":0,"renewal_years":0,"exam_required":False,"is_free":True,
     "sector_ids":["highways","urban_planning"],
     "description":"Free federal training courses covering highway design, safety, and operations at nhi.fhwa.dot.gov."},
    {"id":"faa-atc","name":"FAA Air Traffic Control Specialist","abbreviation":"FAA ATC",
     "org":"FAA","cost_usd":0,"time_months":24,"education_req":"Bachelor's or military ATC",
     "experience_req_years":0,"renewal_years":0,"exam_required":True,"is_free":True,
     "sector_ids":["aviation"],
     "description":"Required federal certification for air traffic controllers."},
    {"id":"aaae-cm","name":"AAAE Certified Member","abbreviation":"CM",
     "org":"AAAE","cost_usd":350,"time_months":6,"education_req":"Bachelor's degree",
     "experience_req_years":1,"renewal_years":3,"exam_required":True,"is_free":False,
     "sector_ids":["aviation"],
     "description":"Key airport management credential from the American Association of Airport Executives."},
    {"id":"fra-rules","name":"FRA Track Safety Standards","abbreviation":"FRA Rules",
     "org":"FRA","cost_usd":0,"time_months":1,"education_req":"None",
     "experience_req_years":0,"renewal_years":3,"exam_required":True,"is_free":True,
     "sector_ids":["railways"],
     "description":"Required federal certification for railroad track inspection and maintenance."},
]

# Role → cert mapping
ROLE_CERTS = {
    "17-2051.00":["pe-license","pmp","fhwa-nhi"],
    "17-2051.01":["pe-license","ptoe","pmp","fhwa-nhi"],
    "19-3051.00":["aicp","pmp"],
    "19-3099.01":["aicp","pmp","fhwa-nhi"],
    "17-1021.00":["gisp"],
    "53-6051.07":["fra-rules"],
    "53-6041.00":["ptoe"],
    "53-2021.00":["faa-atc"],
    "53-2022.00":["aaae-cm"],
    "11-3071.04":["cscp","pmp"],
    "13-1081.00":["cscp"],
    "13-1081.01":["cscp","pmp"],
}


def _get_domain(code: str) -> str:
    for prefix, domain in DOMAIN_MAP.items():
        if code.startswith(prefix):
            return domain
    return "general"


from backend.rag.vector_store import _make_id


async def run_ingestion(data_dir: str = "/app/data/onet"):
    """Main ingestion entry point. Called at startup if Qdrant is empty."""
    from backend.rag.vector_store import ensure_collections, upsert, is_populated
    from backend.rag.embedder import embed_document

    log.info("Starting O*NET ingestion from %s", data_dir)
    ensure_collections()

    onet_path = Path(data_dir)

    # Check files exist
    required = [
        "Occupation_Data.xlsx", "Skills.xlsx", "Task_Statements.xlsx",
        "Technology_Skills.xlsx",
    ]
    missing = [f for f in required if not (onet_path / f).exists()]
    if missing:
        log.warning("O*NET files not found: %s — ingestion skipped", missing)
        log.warning("Place O*NET xlsx files in %s and restart to enable full RAG", data_dir)
        await _ingest_certifications(embed_document)
        return

    try:
        import pandas as pd
        occ_df  = pd.read_excel(onet_path / "Occupation_Data.xlsx")
        sk_df   = pd.read_excel(onet_path / "Skills.xlsx")
        task_df = pd.read_excel(onet_path / "Task_Statements.xlsx")
        tech_df = pd.read_excel(onet_path / "Technology_Skills.xlsx")
        log.info("O*NET files loaded")
    except Exception as e:
        log.error("Failed to load O*NET files: %s", e)
        return

    # Filter to transport codes
    transport_occ = occ_df[occ_df["O*NET-SOC Code"].isin(TRANSPORT_CODES)]
    log.info("Ingesting %d transport occupations", len(transport_occ))

    # ── Roles ──
    role_points = []
    for _, row in transport_occ.iterrows():
        code = row["O*NET-SOC Code"]
        title = row["Title"]
        description = str(row["Description"])
        domain = _get_domain(code)
        wages = BLS_WAGES.get(code, {"entry":"varies","median":"varies","senior":"varies"})

        # Skills for this role
        role_skills = sk_df[
            (sk_df["O*NET-SOC Code"] == code) &
            (sk_df["Scale ID"] == "IM") &
            (sk_df["Data Value"] >= 3.0)
        ].sort_values("Data Value", ascending=False)
        skills = (role_skills[["Element Name","Data Value"]]
                  .drop_duplicates("Element Name")
                  .head(8)
                  .values.tolist())

        # Tasks
        tasks = task_df[
            (task_df["O*NET-SOC Code"] == code) &
            (task_df["Task Type"] == "Core")
        ]["Task"].tolist()[:5]

        # Tech
        role_tech = tech_df[tech_df["O*NET-SOC Code"] == code]
        hot_tech = role_tech[role_tech["Hot Technology"] == "Y"]["Example"].tolist()[:6]
        demand_tech = role_tech[role_tech["In Demand"] == "Y"]["Example"].tolist()[:6]
        tech = list(dict.fromkeys(hot_tech + demand_tech))[:8]

        # Certs
        cert_ids = ROLE_CERTS.get(code, [])

        embed_text = f"{title}. {description[:300]}"
        vector = embed_document(embed_text)

        role_points.append({
            "id": _make_id(code),
            "vector": vector,
            "payload": {
                "onet_code": code,
                "title": title,
                "description": description[:500],
                "domain": domain,
                "sector": SECTOR_LABELS.get(domain, domain),
                "salary_entry":  wages["entry"],
                "salary_median": wages["median"],
                "salary_senior": wages["senior"],
                "skills": [{"name": s[0], "importance": round(float(s[1]),1)} for s in skills],
                "tasks":  tasks,
                "tech":   tech,
                "cert_ids": cert_ids,
            }
        })

    upsert("roles", role_points)
    log.info("Roles ingested: %d", len(role_points))

    # ── Skills ──
    all_skills = sk_df[
        (sk_df["O*NET-SOC Code"].isin(TRANSPORT_CODES)) &
        (sk_df["Scale ID"] == "IM")
    ][["Element ID","Element Name"]].drop_duplicates("Element ID")

    skill_points = []
    for _, row in all_skills.iterrows():
        eid   = row["Element ID"]
        ename = row["Element Name"]
        vector = embed_document(ename)
        skill_points.append({
            "id": _make_id(eid),
            "vector": vector,
            "payload": {"element_id": eid, "name": ename}
        })

    upsert("skills", skill_points)
    log.info("Skills ingested: %d", len(skill_points))

    # ── Tools ──
    transport_tech = tech_df[tech_df["O*NET-SOC Code"].isin(TRANSPORT_CODES)]
    unique_tools = transport_tech[["Example","Commodity Title","Hot Technology","In Demand"]].drop_duplicates("Example")

    tool_points = []
    for _, row in unique_tools.iterrows():
        name   = str(row["Example"])
        cat    = str(row["Commodity Title"])
        vector = embed_document(f"{name} {cat}")
        tool_points.append({
            "id": _make_id(name),
            "vector": vector,
            "payload": {
                "name": name,
                "category": cat,
                "hot": row["Hot Technology"] == "Y",
                "in_demand": row["In Demand"] == "Y",
            }
        })

    upsert("tools", tool_points)
    log.info("Tools ingested: %d", len(tool_points))

    # ── Certifications ──
    await _ingest_certifications(embed_document)

    # ── Career paths ──
    path_points = []
    for i, (from_code, to_code, difficulty, months_min, months_max, notes) in enumerate(CAREER_PATHS):
        from_wages = BLS_WAGES.get(from_code, {})
        to_wages   = BLS_WAGES.get(to_code, {})

        def parse_salary(s: str) -> int:
            try: return int(re.sub(r'[^\d]', '', s.split('k')[0])) * 1000
            except: return 0

        from_med = parse_salary(from_wages.get("median","$0k"))
        to_med   = parse_salary(to_wages.get("median","$0k"))
        delta    = to_med - from_med

        direction = "up" if delta > 5000 else "lateral" if abs(delta) <= 5000 else "pivot"

        embed_text = f"Career transition from {from_code} to {to_code}. {notes}"
        vector = embed_document(embed_text)

        path_points.append({
            "id": i + 1,
            "vector": vector,
            "payload": {
                "from_role_id":      from_code,
                "to_role_id":        to_code,
                "direction":         direction,
                "difficulty":        difficulty,
                "timeline_min":      months_min,
                "timeline_max":      months_max,
                "salary_delta_usd":  delta,
                "notes":             notes,
            }
        })

    upsert("career_paths", path_points)
    log.info("Career paths ingested: %d", len(path_points))
    log.info("O*NET ingestion complete.")


async def _ingest_certifications(embed_document):
    from backend.rag.vector_store import upsert
    cert_points = []
    for cert in CERTIFICATIONS:
        vector = embed_document(f"{cert['name']}. {cert['description']}")
        cert_points.append({
            "id": _make_id(cert["id"]),
            "vector": vector,
            "payload": cert,
        })
    upsert("certifications", cert_points)
    log.info("Certifications ingested: %d", len(cert_points))
