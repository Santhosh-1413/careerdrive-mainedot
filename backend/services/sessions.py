"""In-memory session store. Replace with Redis for production."""

import uuid, time, logging
from backend.core.context import SessionContext

log = logging.getLogger("transitbot.sessions")
_store: dict[str, dict] = {}
SESSION_TTL = 3600


def create_session(model: str = "gpt-4o-mini") -> SessionContext:
    sid = str(uuid.uuid4())
    ctx = SessionContext(session_id=sid, selected_model=model)
    _store[sid] = {"ctx": ctx, "last_access": time.time()}
    log.info("Session created: %s", sid)
    return ctx


def get_session(sid: str) -> SessionContext | None:
    entry = _store.get(sid)
    if not entry: return None
    entry["last_access"] = time.time()
    return entry["ctx"]


def get_or_create(sid: str | None, model: str) -> SessionContext:
    if sid:
        ctx = get_session(sid)
        if ctx:
            ctx.selected_model = model
            return ctx
    return create_session(model)


def delete_session(sid: str):
    _store.pop(sid, None)
