"""
Job Fetcher — USAJobs only (USA-specific).
Uses OPM occupational series codes for precise filtering.
Three-pass search strategy: PositionTitle + series → keyword + series → keyword only.

REQUIRED environment variables:
  USAJOBS_API_KEY   — from developer.usajobs.gov (free registration)
  USAJOBS_EMAIL     — the email you registered with (used as User-Agent)
"""

import os
import uuid
import asyncio
import logging
import httpx
from backend.core.context import JobListing, SessionContext
from backend.core.config import env
from backend.rag.usajobs_codes import build_usajobs_params

log = logging.getLogger("transitbot.jobs")

USAJOBS_URL = "https://data.usajobs.gov/api/search"

_WARNED = False


def _get_usajobs_headers() -> dict | None:
    """
    Build required USAJobs auth headers.
    Returns None if credentials are missing — caller skips the API call.

    USAJobs requires BOTH:
      Authorization-Key: <api key from developer.usajobs.gov>
      User-Agent:        <email address you registered with>

    Register free at: https://developer.usajobs.gov/APIRequest/Index
    """
    global _WARNED
    # strip() + rstrip handles Windows \r\n line endings in .env files
    api_key = env("USAJOBS_API_KEY")
    email   = env("USAJOBS_EMAIL")

    if not api_key or not email:
        if not _WARNED:
            log.warning(
                "USAJobs credentials not configured. "
                "Set USAJOBS_API_KEY and USAJOBS_EMAIL in your .env file. "
                "Register free at https://developer.usajobs.gov/APIRequest/Index"
            )
            _WARNED = True
        return None

    return {
        "Authorization-Key": api_key,
        "User-Agent":        email,
        "Host-Identifier":   "transitbot-v3",
    }


def _parse_salary(rem: list) -> str | None:
    if not rem:
        return None
    mn = rem[0].get("MinimumRange")
    mx = rem[0].get("MaximumRange")
    interval = rem[0].get("RateIntervalCode", "PA")
    if not mn:
        return None
    suffix = "/hr" if interval == "PH" else "/yr"
    return (f"${float(mn):,.0f}–${float(mx):,.0f}{suffix}"
            if mx else f"${float(mn):,.0f}+{suffix}")


def _extract_tags(title: str) -> list[str]:
    t = title.lower()
    tag_map = [
        ("rail","Rail"), ("transit","Transit"), ("highway","Highway"),
        ("aviation","Aviation"), ("port","Maritime"), ("gis","GIS"),
        ("data","Data"), ("engineer","Engineering"), ("planner","Planning"),
        ("policy","Policy"), ("smart","Smart mobility"), ("logistics","Logistics"),
        ("analyst","Analytics"), ("inspector","Inspection"), ("traffic","Traffic"),
    ]
    found = [label for kw, label in tag_map if kw in t]
    return found[:3] or ["Transportation"]


async def fetch_usajobs(
    role: str = "",
    location: str = "",
    domain: str = "",
    keywords: str = "",
    schedule: str = "",
    salary_min: int = 0,
) -> list[JobListing]:

    headers = _get_usajobs_headers()
    if headers is None:
        return []

    remote_only = schedule == "remote"

    async def _search(params: dict) -> list:
        log.info("USAJobs: %s", {k: v for k, v in params.items()})
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(USAJOBS_URL, params=params, headers=headers)
            if r.status_code == 401:
                log.error(
                    "USAJobs 401 Unauthorized — USAJOBS_API_KEY or USAJOBS_EMAIL "
                    "is incorrect. Both must match your account at developer.usajobs.gov"
                )
                return []
            r.raise_for_status()
            return r.json().get("SearchResult", {}).get("SearchResultItems", [])

    # Pass 1 — PositionTitle + OPM series
    params1 = build_usajobs_params(
        role=role, domain=domain, location=location,
        keywords=keywords, results_per_page=8,
        remote_only=remote_only, full_fields=True,
        hiring_path="public",
        min_salary=salary_min if salary_min > 0 else 0,
    )
    items = []
    try:
        items = await _search(params1)
    except Exception as e:
        log.warning("USAJobs pass 1: %s", e)

    # Pass 2 — keyword + series (drop PositionTitle)
    if not items and role:
        try:
            p2 = dict(params1)
            p2.pop("PositionTitle", None)
            p2["Keyword"] = role
            items = await _search(p2)
            log.info("USAJobs pass 2: %d results", len(items))
        except Exception as e:
            log.warning("USAJobs pass 2: %s", e)

    # Pass 3 — keyword only
    if not items:
        try:
            term = role or keywords or domain or "transportation infrastructure"
            p3 = {
                "Keyword": term, "WhoMayApply": "public",
                "ResultsPerPage": 8, "SortField": "OpenDate",
                "SortDirection": "Desc", "Fields": "Full",
            }
            if remote_only:
                p3["RemoteIndicator"] = "True"
            elif params1.get("LocationName"):
                p3["LocationName"] = params1["LocationName"]
            items = await _search(p3)
            log.info("USAJobs pass 3: %d results", len(items))
        except Exception as e:
            log.warning("USAJobs pass 3: %s", e)

    # Parse results
    jobs = []
    for item in items[:6]:
        j = item.get("MatchedObjectDescriptor", {})
        details = j.get("UserArea", {}).get("Details", {})
        desc = (details.get("JobSummary") or
                j.get("QualificationSummary") or
                details.get("MajorDuties") or "")
        close_date = j.get("ApplicationCloseDate", "")[:10]

        jobs.append(JobListing(
            id=j.get("MatchedObjectId", str(uuid.uuid4())),
            title=j.get("PositionTitle", ""),
            company=j.get("DepartmentName") or j.get("OrganizationName", "Federal Agency"),
            location=j.get("PositionLocationDisplay", "USA"),
            source="usajobs",
            url=j.get("PositionURI", "https://usajobs.gov"),
            salary=_parse_salary(j.get("PositionRemuneration", [])),
            description=str(desc)[:400] if desc else "",
            tags=_extract_tags(j.get("PositionTitle", "")),
            close_date=close_date,
        ))

    log.info("USAJobs: %d jobs parsed", len(jobs))
    return jobs


async def fetch_jobs(params: dict, ctx: SessionContext) -> list[JobListing]:
    """
    Fetch jobs from all sources in parallel.
    USAJobs  → federal roles (FHWA, FTA, FRA, FAA, Army Corps)
    Adzuna   → private sector (AECOM, WSP, Jacobs, HDR, Parsons)
    Results are merged and deduplicated by title+company.
    Defaults: domain=transportation, keyword=transportation infrastructure.
    """
    role      = params.get("role") or ctx.profile.current_role or ctx.profile.target_role or ""
    location  = params.get("location") or ctx.profile.location or ""
    domain    = params.get("domain") or ctx.profile.domain or "highways"  # default transport domain
    keywords  = params.get("keywords", "")
    schedule  = params.get("schedule") or ctx.profile.schedule or ""
    salary_min = params.get("salary_min", 0)

    # If no role or keywords specified, default to transportation infrastructure search
    if not role and not keywords:
        keywords = "transportation infrastructure"

    # Lazy import to avoid circular imports at module load time
    from backend.services.adzuna import fetch_adzuna

    # Run both sources in parallel
    usajobs_result, adzuna_result = await asyncio.gather(
        fetch_usajobs(
            role=role, location=location, domain=domain,
            keywords=keywords, schedule=schedule, salary_min=salary_min,
        ),
        fetch_adzuna(
            role=role, location=location, domain=domain,
            keywords=keywords, schedule=schedule, salary_min=salary_min,
        ),
        return_exceptions=True,
    )

    # Handle exceptions from either source
    usajobs_jobs = usajobs_result if isinstance(usajobs_result, list) else []
    adzuna_jobs  = adzuna_result  if isinstance(adzuna_result,  list) else []

    if isinstance(usajobs_result, Exception):
        log.warning("USAJobs fetch error: %s", usajobs_result)
    if isinstance(adzuna_result, Exception):
        log.warning("Adzuna fetch error: %s", adzuna_result)

    # Merge — USAJobs first (federal), then Adzuna (private sector)
    all_jobs = usajobs_jobs + adzuna_jobs

    # Deduplicate by normalised title+company
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = (job.title.lower().strip()[:40], job.company.lower().strip()[:30])
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    log.info("Jobs merged: %d USAJobs + %d Adzuna = %d unique",
             len(usajobs_jobs), len(adzuna_jobs), len(unique_jobs))
    return unique_jobs[:10]  # cap at 10 total listings
