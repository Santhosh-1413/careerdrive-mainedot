"""
TransitBot v3
=============
POST /api/chat      — main conversational endpoint
POST /api/resume    — resume upload and parsing
GET  /api/session/{id}
POST /api/session/{id}/save-job
GET  /health
GET  /              — serves frontend
"""

import os, re, json, logging, asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.core.context import SessionContext
from backend.core.llm import generate
from backend.core.prompts import build_system_prompt
from backend.services.intent import classify
from backend.services.jobs import fetch_jobs
from backend.services.resume import extract_text, build_profile_from_resume
from backend.services.sessions import get_or_create, get_session, delete_session
from backend.rag.retriever import retrieve
from backend.rag.job_boards import format_boards_for_prompt, get_boards

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("transitbot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("TransitBot v3 starting...")
    # Ingest O*NET data into Qdrant on startup if empty
    try:
        from backend.rag.vector_store import is_populated
        from backend.rag.ingest import run_ingestion

        if not is_populated():
            log.info("Qdrant empty — running O*NET ingestion...")
            data_dir = os.environ.get("ONET_DATA_DIR", "/app/data/onet")
            await run_ingestion(data_dir)
        else:
            from backend.rag.vector_store import collection_count

            log.info("Qdrant ready — %d roles loaded", collection_count("roles"))
    except Exception as e:
        log.warning("Qdrant ingestion skipped: %s", e)
    yield
    log.info("TransitBot v3 shutting down.")


app = FastAPI(title="TransitBot API v3", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_RESUME_MB = 5


# ── Schemas ────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    module: str = "general"
    model: str = "gpt-4o-mini"
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    intent: str
    module: str
    jobs: list[dict] = []
    map_node: Optional[dict] = None
    boards: list[dict] = []
    profile_updated: bool = False


# ── /api/chat ──────────────────────────────────────────────────────────────────


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):

    # 1. Session
    ctx = get_or_create(req.session_id, req.model)
    # 2. Intent + params (local, no API cost)
    ir = classify(req.message)

    # Derive effective module — trust frontend tab selection over intent classifier
    effective_module = req.module if req.module != "general" else ir.module
    ctx.active_module = effective_module

    # 3. Capture context from this message
    p = ir.params
    if p.get("role") and not ctx.profile.current_role:
        ctx.profile.current_role = p["role"]
    if p.get("location") and not ctx.profile.location:
        ctx.profile.location = p["location"]
    if p.get("state_code") and not ctx.profile.state_code:
        ctx.profile.state_code = p["state_code"]
    if p.get("sector") and not ctx.profile.sector:
        ctx.profile.sector = p["sector"]
    if p.get("domain") and not ctx.profile.domain:
        ctx.profile.domain = p["domain"]
    if p.get("experience") and not ctx.profile.experience_label:
        ctx.profile.experience_label = p["experience"]
    if p.get("salary_min") and not ctx.profile.salary_min:
        ctx.profile.salary_min = p["salary_min"]
    if p.get("schedule") and not ctx.profile.schedule:
        ctx.profile.schedule = p["schedule"]

    ctx.add_message("user", req.message, module=effective_module)

    # 4. Fetch live jobs if job search intent
    fetched_jobs = []

    # Detect follow-up replies — user answered a clarifying question
    # e.g. previous turn asked "which state?" and user replied "texas"
    is_followup_location = (
        ir.intent == "general"
        and ir.extracted.location
        and not ir.extracted.role
        and (ctx.profile.current_role or ctx.profile.domain or ctx.profile.sector)
        and len(req.message.strip().split())
        <= 4  # short reply = likely a clarifying answer
    )
    # Detect follow-up role reply — user answered "what role?" with just a role name
    is_followup_role = (
        ir.intent == "general"
        and ir.extracted.role
        and not ir.extracted.location
        and effective_module == "job_finder"
        and len(req.message.strip().split()) <= 5
    )

    if is_followup_location:
        log.info(
            "Follow-up location detected: '%s' — continuing job search",
            ir.extracted.location,
        )
        ir.intent = "job_search"
        # Use profile role/domain since user didn't repeat it
        if not p.get("role"):
            p["role"] = ctx.profile.current_role or ""
        if not p.get("domain"):
            p["domain"] = ctx.profile.domain or ""
        if not p.get("sector"):
            p["sector"] = ctx.profile.sector or ""

    if is_followup_role:
        log.info(
            "Follow-up role detected: '%s' — triggering job search", ir.extracted.role
        )
        ir.intent = "job_search"

    should_search = ir.intent in ("job_search", "onet_lookup") or (
        effective_module == "job_finder" and ir.intent not in ("general",)
    )
    if should_search:
        search_params = dict(p)
        if not search_params.get("role") and ctx.profile.current_role:
            search_params["role"] = ctx.profile.current_role
        if not search_params.get("location") and ctx.profile.location:
            search_params["location"] = ctx.profile.location
        fetched_jobs = await fetch_jobs(search_params, ctx)
        if fetched_jobs:
            ctx.fetched_jobs = fetched_jobs
            log.info(
                "Jobs fetched: %d total (%d USAJobs, %d Adzuna)",
                len(fetched_jobs),
                sum(1 for j in fetched_jobs if j.source == "usajobs"),
                sum(1 for j in fetched_jobs if j.source == "adzuna"),
            )

    # 5. RAG retrieval from Qdrant
    rag_context = ""
    if ir.intent != "general":
        try:
            rag_context = await retrieve(
                user_message=req.message,
                current_role=ctx.profile.current_role,
                target_role=ctx.profile.target_role,
                domain=ctx.profile.domain,
                user_skills=ctx.profile.skills,
                intent=ir.intent,
            )
        except Exception as e:
            log.warning("RAG retrieval failed: %s", e)

    # 6. Job board recommendations
    boards_text = format_boards_for_prompt(
        domain=ctx.profile.domain or p.get("domain", ""),
        location=ctx.profile.location or p.get("location", ""),
    )
    if boards_text:
        rag_context = (rag_context + "\n\n" + boards_text).strip()

    board_links = get_boards(
        domain=ctx.profile.domain or p.get("domain", ""),
        location=ctx.profile.location or p.get("location", ""),
    )

    # 7. Build system prompt
    # Explicitly inject fetched jobs into rag_context so LLM sees them clearly
    if fetched_jobs:
        jobs_block = "\n\n=== LIVE JOB LISTINGS RETRIEVED NOW ===\n"
        jobs_block += f"Found {len(fetched_jobs)} real job listings. Reference these specifically in your response:\n"
        for j in fetched_jobs[:8]:
            jobs_block += f"\n• {j.title} | {j.company} | {j.location}"
            if j.salary:
                jobs_block += f" | {j.salary}"
            if j.source == "usajobs":
                jobs_block += " [Federal]"
            if j.source == "adzuna":
                jobs_block += " [Private sector]"
            if j.close_date:
                jobs_block += f" | closes {j.close_date}"
            if j.description:
                jobs_block += f"\n  {j.description[:150]}"
        jobs_block += "\n\nDo NOT say you have no listings. You have the listings above. Summarise them and help the user choose."
        rag_context = (rag_context + jobs_block).strip()

    system = build_system_prompt(ctx, rag_context=rag_context)

    # 8. Grounding guards
    if p.get("non_us_mentioned"):
        system += (
            "\n\nNOTE: User mentioned a non-US location. "
            "Remind them TransitBot focuses on US transportation careers. "
            "Offer to search a US state instead."
        )

    if ir.intent == "job_search" and not fetched_jobs:
        searched = p.get("role") or p.get("keywords") or "transportation roles"
        loc = p.get("location") or "USA"
        from backend.services.jobs import _get_usajobs_headers

        creds_ok = _get_usajobs_headers() is not None
        if not creds_ok:
            creds_msg = (
                "USAJobs API credentials are not configured on this server. "
                "Tell the user that live job search is temporarily unavailable, "
                "and suggest the job boards listed above. "
                "Do NOT suggest any other websites, URLs, or boards beyond what is listed above. "
                "Do NOT invent any job boards, company career pages, or university job boards."
            )
        else:
            creds_msg = (
                f"The live search for '{searched}' in '{loc}' returned no results right now. "
                "This may be temporary. Suggest the verified job boards listed above. "
                "Do NOT invent additional websites, URLs, or job boards beyond the list above."
            )
        system += f"\n\nIMPORTANT — NO JOBS FOUND: {creds_msg}"

    # 9. LLM call
    try:
        reply = await generate(
            system=system,
            messages=ctx.to_llm_messages(),
            model=req.model,
            max_tokens=1000,
        )
    except Exception as e:
        log.error("LLM error: %s", e)
        raise HTTPException(502, f"Model error: {e}")

    # 10. Parse structured outputs from LLM
    reply, map_node = _extract_map_node(reply)
    reply, job_search_tag = _extract_job_search(reply)

    # If LLM emitted a job_search tag, trigger a fetch
    if job_search_tag and not fetched_jobs:
        fetched_jobs = await fetch_jobs(job_search_tag, ctx)
        if fetched_jobs:
            ctx.fetched_jobs = fetched_jobs

    ctx.add_message("assistant", reply, module=effective_module)

    return ChatResponse(
        reply=reply,
        session_id=ctx.session_id,
        intent=ir.intent,
        module=effective_module,
        jobs=[_job_dict(j) for j in fetched_jobs],
        map_node=map_node,
        # boards=board_links,
        profile_updated=bool(fetched_jobs or map_node),
    )


# ── /api/resume ────────────────────────────────────────────────────────────────


@app.post("/api/resume")
async def upload_resume(
    file: UploadFile = File(...),
    session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    model: str = Header("gpt-4o-mini", alias="X-Model"),
):
    ctx = get_or_create(session_id, model)
    data = await file.read()
    if len(data) > MAX_RESUME_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_RESUME_MB}MB")

    try:
        text = extract_text(data, file.filename or "", file.content_type or "")
    except ValueError as e:
        raise HTTPException(415, str(e))

    if len(text.strip()) < 50:
        raise HTTPException(422, "Text too short — file may be scanned/image-only")

    ctx.resume_text = text
    ctx.resume_filename = file.filename

    try:
        profile = await build_profile_from_resume(
            text=text, llm_generate=generate, model=model
        )
        ctx.profile = profile
    except Exception as e:
        log.error("Profile build failed: %s", e)

    return JSONResponse(
        {
            "ok": True,
            "session_id": ctx.session_id,
            "profile": _profile_dict(ctx.profile),
            "chars_extracted": len(text),
        }
    )


# ── /api/session ───────────────────────────────────────────────────────────────


@app.get("/api/session/{session_id}")
def get_session_state(session_id: str):
    ctx = get_session(session_id)
    if not ctx:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": ctx.session_id,
        "profile": _profile_dict(ctx.profile),
        "has_resume": ctx.resume_text is not None,
        "saved_jobs_count": len(ctx.saved_jobs),
        "fetched_jobs_count": len(ctx.fetched_jobs),
        "message_count": len(ctx.messages),
        "active_module": ctx.active_module,
    }


@app.delete("/api/session/{session_id}")
def clear_session(session_id: str):
    delete_session(session_id)
    return {"ok": True}


@app.post("/api/session/{session_id}/save-job")
def save_job(session_id: str, job_id: str):
    ctx = get_session(session_id)
    if not ctx:
        raise HTTPException(404, "Session not found")
    job = next((j for j in ctx.fetched_jobs if j.id == job_id), None)
    if job:
        job.saved = True
        if job not in ctx.saved_jobs:
            ctx.saved_jobs.append(job)
        if not ctx.profile.target_role:
            ctx.profile.target_role = job.title
    return {"ok": True}


# ── /health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    from backend.rag.vector_store import collection_count
    from backend.rag.embedder import get_model_name
    from backend.core.llm import is_openai_available, is_ollama_available

    try:
        roles = collection_count("roles")
    except:
        roles = 0
    from backend.core.config import env as _env

    usajobs_key = bool(_env("USAJOBS_API_KEY"))
    usajobs_email = bool(_env("USAJOBS_EMAIL"))
    adzuna_id = bool(_env("ADZUNA_APP_ID"))
    adzuna_key = bool(_env("ADZUNA_APP_KEY"))
    setup_needed = []
    if not usajobs_key:
        setup_needed.append("USAJOBS_API_KEY")
    if not usajobs_email:
        setup_needed.append("USAJOBS_EMAIL")
    if not adzuna_id:
        setup_needed.append("ADZUNA_APP_ID")
    if not adzuna_key:
        setup_needed.append("ADZUNA_APP_KEY")
    return {
        "status": "ok",
        "qdrant_roles": roles,
        "embed_model": get_model_name() if roles > 0 else "not loaded",
        "openai": is_openai_available(),
        "ollama": is_ollama_available(),
        "usajobs_ready": usajobs_key and usajobs_email,
        "adzuna_ready": adzuna_id and adzuna_key,
        "setup_needed": setup_needed,
    }


# ── Frontend ───────────────────────────────────────────────────────────────────

_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
_index_path = os.path.join(_frontend_dir, "index.html")

if os.path.isdir(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/")
def serve_frontend():
    if os.path.exists(_index_path):
        return FileResponse(_index_path)
    raise HTTPException(
        404, "Frontend not found. Place index.html in the frontend/ folder."
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _extract_map_node(text: str) -> tuple[str, Optional[dict]]:
    m = re.search(r"<map_node>(.*?)</map_node>", text, re.DOTALL)
    if not m:
        return text, None
    try:
        node = json.loads(m.group(1).strip())
        return (text[: m.start()] + text[m.end() :]).strip(), node
    except:
        return text, None


def _extract_job_search(text: str) -> tuple[str, Optional[dict]]:
    m = re.search(r"<job_search>(.*?)</job_search>", text, re.DOTALL)
    if not m:
        return text, None
    try:
        params = json.loads(m.group(1).strip())
        return (text[: m.start()] + text[m.end() :]).strip(), params
    except:
        return text, None


def _job_dict(j) -> dict:
    return {
        "id": j.id,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "source": j.source,
        "url": j.url,
        "salary": j.salary,
        "tags": j.tags,
        "match_score": round(j.match_score, 2),
        "saved": j.saved,
        "close_date": j.close_date,
        "description": j.description,
    }


def _profile_dict(p) -> dict:
    return {
        "name": p.name,
        "current_role": p.current_role,
        "target_role": p.target_role,
        "experience_years": p.experience_years,
        "experience_label": p.experience_label,
        "sector": p.sector,
        "domain": p.domain,
        "location": p.location,
        "state_code": p.state_code,
        "skills": p.skills,
        "skill_gaps": p.skill_gaps,
        "certifications": p.certifications,
        "schedule": p.schedule,
        "salary_min": p.salary_min,
    }
