"""
RAG Retriever
==============
All Qdrant queries used by the chat endpoint.
Returns formatted context strings ready for LLM injection.
"""

import logging
from backend.rag.embedder import embed_query
from backend.rag.vector_store import search, get_by_id, get_by_ids, filter_search, _make_id

log = logging.getLogger("transitbot.retriever")


# ── Role lookup ────────────────────────────────────────────────────────────────

def find_role(query: str, domain: str = "", limit: int = 3) -> list[dict]:
    """Semantic search for roles matching a query string."""
    vector = embed_query(query)
    filters = {"domain": domain} if domain else {}
    results = search("roles", vector, limit=limit, filters=filters if filters else None)
    return [r.payload for r in results]


def get_role(onet_code: str) -> dict | None:
    """Get a role profile by exact O*NET code."""
    try:
        return get_by_id("roles", _make_id(onet_code))
    except Exception:
        # Fallback: semantic search by code string
        results = find_role(onet_code, limit=1)
        return results[0] if results else None


# ── Skill gap ──────────────────────────────────────────────────────────────────

def get_skill_gap(
    from_role_code: str,
    to_role_code: str,
    user_skills: list[str],
) -> dict:
    """
    Compare skills required by target role against user's current skills.
    Returns missing skills ranked by importance.
    """
    from_role = get_by_id("roles", _make_id(from_role_code)) or {}
    to_role   = get_by_id("roles", _make_id(to_role_code))   or {}

    to_skills   = to_role.get("skills", [])
    from_skills = from_role.get("skills", [])

    user_lower = {s.lower() for s in user_skills}

    missing = []
    for skill in to_skills:
        name = skill.get("name", "")
        imp  = skill.get("importance", 0)
        if name.lower() not in user_lower:
            # Check if from_role already covers it
            covered = any(fs.get("name","").lower() == name.lower() for fs in from_skills)
            missing.append({
                "name": name,
                "importance": imp,
                "new_skill": not covered,
            })

    missing.sort(key=lambda x: (-x["importance"], not x["new_skill"]))
    return {
        "from_role": from_role.get("title", from_role_code),
        "to_role":   to_role.get("title", to_role_code),
        "missing_skills": missing[:8],
        "target_certs":   to_role.get("cert_ids", []),
        "target_tech":    to_role.get("tech", [])[:5],
    }


# ── Career path ────────────────────────────────────────────────────────────────

def get_career_paths(from_role_code: str) -> list[dict]:
    """Get all career paths from a given role."""
    results = filter_search("career_paths", {"from_role_id": from_role_code}, limit=10)
    return results


def find_career_path(from_code: str, to_code: str) -> dict | None:
    """Find the specific path between two roles."""
    paths = filter_search("career_paths", {
        "from_role_id": from_code,
        "to_role_id":   to_code,
    }, limit=1)
    return paths[0] if paths else None


# ── Certifications ─────────────────────────────────────────────────────────────

def get_certs_for_role(role_code: str) -> list[dict]:
    """Get certifications recommended for a role."""
    role = get_role(role_code)
    if not role:
        return []
    cert_ids = role.get("cert_ids", [])
    return get_by_ids("certifications", cert_ids)


def search_certs(query: str, sector: str = "") -> list[dict]:
    """Semantic cert search, optionally filtered by sector."""
    vector = embed_query(query)
    results = search("certifications", vector, limit=4)
    certs = [r.payload for r in results]
    if sector:
        certs = [c for c in certs if sector in c.get("sector_ids", [])]
    return certs


# ── Context builders ───────────────────────────────────────────────────────────

def build_role_context(role_payload: dict) -> str:
    """Format a role payload for LLM injection."""
    if not role_payload:
        return ""
    lines = [
        f"O*NET Role: {role_payload.get('title','')} ({role_payload.get('onet_code','')})",
        f"Sector: {role_payload.get('sector','')}",
        f"About: {role_payload.get('description','')[:200]}",
        "",
        "Required skills:",
    ]
    for s in role_payload.get("skills", [])[:6]:
        stars = "★" * round(s.get("importance", 3))
        lines.append(f"  • {s['name']} {stars}")

    tasks = role_payload.get("tasks", [])[:4]
    if tasks:
        lines += ["", "Typical tasks:"]
        for t in tasks:
            lines.append(f"  • {t[:100]}")

    tech = role_payload.get("tech", [])[:5]
    if tech:
        lines += ["", f"Key tools: {', '.join(tech)}"]

    wages = role_payload.get
    lines += [
        "",
        f"Salary (BLS 2023): Entry {role_payload.get('salary_entry','—')} | "
        f"Median {role_payload.get('salary_median','—')} | "
        f"Senior {role_payload.get('salary_senior','—')}",
    ]
    return "\n".join(lines)


def build_career_path_context(path: dict, from_role: dict, to_role: dict) -> str:
    """Format a career path for LLM injection."""
    if not path:
        return ""
    direction_label = {"up":"Upward move","lateral":"Lateral move","pivot":"Career pivot"}.get(
        path.get("direction",""), "Transition"
    )
    delta = path.get("salary_delta_usd", 0)
    delta_str = f"+${delta:,}" if delta > 0 else f"${delta:,}" if delta < 0 else "similar salary"
    return (
        f"Career path: {from_role.get('title','')} → {to_role.get('title','')}\n"
        f"Type: {direction_label} | Difficulty: {path.get('difficulty',3)}/5 | "
        f"Timeline: {path.get('timeline_min',6)}–{path.get('timeline_max',18)} months | "
        f"Salary delta: {delta_str}\n"
        f"Notes: {path.get('notes','')}"
    )


def build_cert_context(certs: list[dict]) -> str:
    """Format certifications for LLM injection."""
    if not certs:
        return ""
    lines = ["Relevant certifications:"]
    for c in certs:
        free = " (FREE)" if c.get("is_free") else f" (~${c.get('cost_usd',0):,})"
        time = f"{c.get('time_months',0)} months prep"
        lines.append(f"  • {c['name']} ({c['abbreviation']}) — {c['org']}{free}, {time}")
        lines.append(f"    {c.get('description','')[:100]}")
    return "\n".join(lines)


# ── Main retrieve function ─────────────────────────────────────────────────────

async def retrieve(
    user_message: str,
    current_role: str = "",
    target_role: str = "",
    domain: str = "",
    user_skills: list[str] = None,
    intent: str = "general",
) -> str:
    """
    Main retrieval entry point.
    Returns a formatted context string for the system prompt.
    """
    if intent == "general":
        return ""

    blocks = []

    # Find relevant roles
    from_roles = find_role(current_role or user_message, domain=domain, limit=2) if current_role or domain else []
    to_roles   = find_role(target_role, domain=domain, limit=2) if target_role else []

    # Also search the message itself for role mentions
    if not from_roles:
        from_roles = find_role(user_message, domain=domain, limit=2)

    # Role context
    if from_roles:
        blocks.append(build_role_context(from_roles[0]))
    if to_roles and to_roles[0] != (from_roles[0] if from_roles else None):
        blocks.append(build_role_context(to_roles[0]))

    # Career path between roles
    if from_roles and to_roles:
        from_code = from_roles[0].get("onet_code","")
        to_code   = to_roles[0].get("onet_code","")
        if from_code and to_code:
            path = find_career_path(from_code, to_code)
            if path:
                blocks.append(build_career_path_context(path, from_roles[0], to_roles[0]))

            # Skill gap
            if intent in ("career_advice","skill_gap") and user_skills is not None:
                gap = get_skill_gap(from_code, to_code, user_skills)
                if gap["missing_skills"]:
                    lines = [f"Skill gap ({from_roles[0].get('title','')} → {to_roles[0].get('title','')}):"]
                    for s in gap["missing_skills"][:6]:
                        flag = " ← NEW" if s["new_skill"] else ""
                        lines.append(f"  • {s['name']} (importance {s['importance']:.1f}){flag}")
                    blocks.append("\n".join(lines))

    # Certifications
    if intent in ("career_advice","skill_gap","onet_lookup"):
        role_code = (from_roles[0].get("onet_code","") if from_roles else
                     to_roles[0].get("onet_code","") if to_roles else "")
        if role_code:
            certs = get_certs_for_role(role_code)
        else:
            certs = search_certs(user_message, sector=domain)
        if certs:
            blocks.append(build_cert_context(certs[:3]))

    if not blocks:
        return ""

    header = "=== O*NET Career Knowledge (verified data) ===\n"
    return header + "\n\n---\n\n".join(blocks)
