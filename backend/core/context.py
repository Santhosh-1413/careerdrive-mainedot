"""
Shared session context — single source of truth per user conversation.
Held in memory, keyed by session_id.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class UserProfile:
    name: str = "User"
    current_role: str = ""
    current_onet_code: str = ""
    target_role: str = ""
    target_onet_code: str = ""
    experience_years: int = 0
    experience_label: str = ""
    sector: str = ""
    domain: str = ""
    location: str = ""
    state_code: str = ""
    skills: list[str] = field(default_factory=list)
    skill_gaps: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    career_goals: list[str] = field(default_factory=list)
    salary_min: int = 0
    salary_max: int = 0
    schedule: str = ""      # remote / hybrid / onsite


@dataclass
class JobListing:
    id: str
    title: str
    company: str
    location: str
    source: str             # usajobs / adzuna
    url: str
    salary: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    match_score: float = 0.0
    saved: bool = False
    close_date: str = ""


@dataclass
class ConversationMessage:
    role: str               # user / assistant
    content: str
    module: str = "general"
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionContext:
    session_id: str = ""
    profile: UserProfile = field(default_factory=UserProfile)
    resume_text: Optional[str] = None
    resume_filename: Optional[str] = None
    fetched_jobs: list[JobListing] = field(default_factory=list)
    saved_jobs: list[JobListing] = field(default_factory=list)
    messages: list[ConversationMessage] = field(default_factory=list)
    active_module: str = "general"
    selected_model: str = "gpt-4o-mini"

    def to_llm_messages(self) -> list[dict]:
        return [
            {"role": m.role, "content": m.content}
            for m in self.messages[-8:]
        ]

    def add_message(self, role: str, content: str, module: str = "general"):
        self.messages.append(ConversationMessage(
            role=role, content=content, module=module
        ))

    def get_profile_summary(self) -> str:
        p = self.profile
        parts = []
        if p.current_role:  parts.append(f"Current role: {p.current_role}")
        if p.target_role:   parts.append(f"Target role: {p.target_role}")
        if p.experience_label: parts.append(f"Experience: {p.experience_label}")
        if p.sector:        parts.append(f"Sector: {p.sector}")
        if p.location:      parts.append(f"Location: {p.location}")
        if p.skills:        parts.append(f"Skills: {', '.join(p.skills[:8])}")
        if p.skill_gaps:    parts.append(f"Skill gaps: {', '.join(p.skill_gaps[:4])}")
        if p.certifications: parts.append(f"Certs: {', '.join(p.certifications)}")
        if p.schedule:      parts.append(f"Work preference: {p.schedule}")
        if p.salary_min:    parts.append(f"Target salary: ${p.salary_min:,}+")
        if self.saved_jobs:
            parts.append(f"Saved jobs: {', '.join(j.title for j in self.saved_jobs[:3])}")
        return "\n".join(parts) if parts else "No profile yet."

    def get_recent_jobs_text(self) -> str:
        if not self.fetched_jobs:
            return ""
        lines = ["Recent job listings retrieved from USAJobs:"]
        for j in self.fetched_jobs[:6]:
            line = f"- {j.title} | {j.company} | {j.location}"
            if j.salary:   line += f" | {j.salary}"
            if j.close_date: line += f" | closes {j.close_date}"
            lines.append(line)
        return "\n".join(lines)
