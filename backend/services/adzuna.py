"""
Adzuna Job Fetcher — US private sector transportation jobs.
Complements USAJobs (federal) with private sector listings from
firms like AECOM, WSP, Jacobs, HDR, Parsons, Bechtel.

API docs: https://developer.adzuna.com/overview
Free tier: generous rate limits, instant registration.
"""

import logging
import httpx
import uuid
from backend.core.context import JobListing
from backend.core.config import env

log = logging.getLogger("transitbot.adzuna")

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/us/search/1"

# Transport-specific category tags Adzuna recognises
ADZUNA_CATEGORIES = {
    "highways":       "engineering-jobs",
    "railways":       "engineering-jobs",
    "aviation":       "engineering-jobs",
    "maritime":       "engineering-jobs",
    "logistics":      "logistics-warehouse-jobs",
    "urban_planning": "engineering-jobs",
    "public_transit": "engineering-jobs",
    "general":        "engineering-jobs",
}

_WARNED = False


def _get_adzuna_creds() -> tuple[str, str] | tuple[None, None]:
    global _WARNED
    app_id  = env("ADZUNA_APP_ID")
    app_key = env("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        if not _WARNED:
            log.warning(
                "Adzuna credentials not configured. "
                "Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env. "
                "Register free at https://developer.adzuna.com"
            )
            _WARNED = True
        return None, None
    return app_id, app_key


def _extract_tags(title: str) -> list[str]:
    t = title.lower()
    tag_map = [
        ("rail", "Rail"), ("transit", "Transit"), ("highway", "Highway"),
        ("aviation", "Aviation"), ("port", "Maritime"), ("gis", "GIS"),
        ("data", "Data"), ("engineer", "Engineering"), ("planner", "Planning"),
        ("logistics", "Logistics"), ("analyst", "Analytics"),
        ("inspector", "Inspection"), ("traffic", "Traffic"),
        ("smart", "Smart mobility"), ("supply chain", "Supply chain"),
    ]
    found = [label for kw, label in tag_map if kw in t]
    return found[:3] or ["Transportation"]


async def fetch_adzuna(
    role: str = "",
    location: str = "",
    domain: str = "",
    keywords: str = "",
    schedule: str = "",
    salary_min: int = 0,
) -> list[JobListing]:
    """
    Search Adzuna for US transportation jobs.
    Returns private sector listings to complement USAJobs federal results.
    """
    app_id, app_key = _get_adzuna_creds()
    if not app_id:
        return []

    # Domain → keyword mapping (used when no role specified)
    DOMAIN_KEYWORDS = {
        "highways":       "transportation engineer highway",
        "railways":       "rail transit engineer",
        "aviation":       "aviation engineer FAA",
        "maritime":       "maritime port logistics",
        "logistics":      "logistics supply chain",
        "urban_planning": "urban planner GIS",
        "public_transit": "transit planner FTA",
    }

    # Build search query — always defaults to transportation infrastructure
    query_parts = []
    if role:
        query_parts.append(role)
    elif keywords:
        query_parts.append(keywords)
    else:
        # Default: use domain keyword or generic transport fallback
        query_parts.append(DOMAIN_KEYWORDS.get(domain, "transportation infrastructure"))

    query = " ".join(query_parts)

    params: dict = {
        "app_id":         app_id,
        "app_key":        app_key,
        "results_per_page": 8,
        "what":           query,
        "content-type":   "application/json",
        "sort_by":        "date",
    }

    # Location — Adzuna uses city name or state
    remote_only = schedule == "remote"
    if remote_only:
        params["where"] = "remote"
    elif location and location.lower() not in ("remote", "anywhere", "usa", "us", ""):
        params["where"] = location

    # Salary filter
    if salary_min > 0:
        params["salary_min"] = salary_min

    # Category
    category = ADZUNA_CATEGORIES.get(domain, "engineering-jobs")
    params["category"] = category

    log.info("Adzuna search: query='%s' location='%s' category='%s'",
             query, location, category)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(ADZUNA_URL, params=params)

            if r.status_code == 401:
                log.error("Adzuna 401 — check ADZUNA_APP_ID and ADZUNA_APP_KEY")
                return []
            if r.status_code == 403:
                log.error("Adzuna 403 — API key may be inactive or rate limited")
                return []

            r.raise_for_status()
            data = r.json()

        results = data.get("results", [])
        jobs = []

        for item in results[:6]:
            # Salary
            salary = None
            sal_min = item.get("salary_min")
            sal_max = item.get("salary_max")
            if sal_min:
                salary = (f"${float(sal_min):,.0f}–${float(sal_max):,.0f}/yr"
                          if sal_max else f"${float(sal_min):,.0f}+/yr")

            # Location
            loc_obj = item.get("location", {})
            loc_parts = loc_obj.get("display_name", "") or ", ".join(
                a.get("display_name", "") for a in loc_obj.get("area", [])[-2:]
            )

            # Company
            company = item.get("company", {}).get("display_name", "Private employer")

            # Description — Adzuna gives a snippet
            description = item.get("description", "")[:400]

            jobs.append(JobListing(
                id=str(item.get("id", uuid.uuid4())),
                title=item.get("title", ""),
                company=company,
                location=loc_parts or "USA",
                source="adzuna",
                url=item.get("redirect_url", "https://adzuna.com"),
                salary=salary,
                description=description,
                tags=_extract_tags(item.get("title", "")),
                close_date="",
            ))

        log.info("Adzuna: %d jobs parsed for query='%s'", len(jobs), query)
        return jobs

    except httpx.TimeoutException:
        log.warning("Adzuna request timed out")
        return []
    except Exception as e:
        log.warning("Adzuna error: %s", e)
        return []
