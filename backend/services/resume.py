"""Resume parser — text extraction + LLM profile builder."""

import io, re, json, logging
from typing import Optional
from backend.core.context import UserProfile

log = logging.getLogger("transitbot.resume")

try:
    import pdfplumber; PDF_OK = True
except ImportError:
    PDF_OK = False

try:
    import docx as python_docx; DOCX_OK = True
except ImportError:
    DOCX_OK = False


def extract_text(data: bytes, filename: str, content_type: str) -> str:
    fname = filename.lower()
    mime  = (content_type or "").lower()

    if "pdf" in mime or fname.endswith(".pdf"):
        if not PDF_OK: raise ValueError("pdfplumber not installed")
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)

    if "wordprocessingml" in mime or fname.endswith(".docx"):
        if not DOCX_OK: raise ValueError("python-docx not installed")
        doc = python_docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if "text" in mime or fname.endswith(".txt"):
        for enc in ("utf-8", "latin-1", "cp1252"):
            try: return data.decode(enc)
            except UnicodeDecodeError: continue

    raise ValueError(f"Unsupported file type: {mime or fname}")


PROFILE_PROMPT = """Parse this resume for a US transportation career platform.
Return ONLY valid JSON, no markdown:
{{
  "name": "full name or Candidate",
  "current_role": "most recent job title",
  "experience_years": integer,
  "experience_label": one of ["Less than 1 year","1-3 years","3-7 years","7+ years"],
  "sector": one of ["Rail & transit","Highways & roads","Aviation","Ports & maritime","Smart mobility","Logistics","Urban planning","General"],
  "domain": one of ["railways","highways","aviation","maritime","logistics","urban_planning","general"],
  "location": "city, state",
  "state_code": "2-letter US state code",
  "skills": ["skill1",...],
  "skill_gaps": ["gap1","gap2","gap3"],
  "certifications": ["cert1",...],
  "career_goals": [],
  "salary_min": 0,
  "schedule": "remote|hybrid|onsite|"
}}

Resume:
\"\"\"
{text}
\"\"\"
"""


async def build_profile_from_resume(
    text: str,
    llm_generate,
    model: str,
) -> UserProfile:
    try:
        raw = await llm_generate(
            system="You are a resume parser. Return only valid JSON.",
            messages=[{"role": "user", "content": PROFILE_PROMPT.format(text=text[:3500])}],
            model=model,
            max_tokens=700,
        )
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw)
        d = json.loads(raw)
        return UserProfile(
            name=d.get("name","Candidate"),
            current_role=d.get("current_role",""),
            experience_years=d.get("experience_years",0),
            experience_label=d.get("experience_label",""),
            sector=d.get("sector",""),
            domain=d.get("domain",""),
            location=d.get("location",""),
            state_code=d.get("state_code",""),
            skills=d.get("skills",[]),
            skill_gaps=d.get("skill_gaps",[]),
            certifications=d.get("certifications",[]),
            career_goals=d.get("career_goals",[]),
            salary_min=d.get("salary_min",0),
            schedule=d.get("schedule",""),
        )
    except Exception as e:
        log.error("Profile extraction failed: %s", e)
        return UserProfile()
