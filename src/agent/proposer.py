# src/agent/proposer.py
"""One structured-output call to Claude that returns a SetupProposal, plus JSONL logging."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agent.schema import GeometrySummary, SetupProposal

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
DEFAULT_LOG = Path("logs/proposals.jsonl")
_PLAYBOOK_PATH = Path(__file__).parent / "playbook.md"

_LOG_LOCK = threading.Lock()


def append_jsonl(path: Path, row: dict) -> None:
    """Append one JSON row to a JSONL log.

    FastAPI runs the sync /propose and /revise handlers in a threadpool, so
    multiple requests can log concurrently; a bare read-modify-write (or even
    a bare open/append without the lock) can interleave and corrupt the file
    under contention. All writers to the proposal log go through this one
    helper, serialised by a single module-level lock, so the log is safe to
    treat as append-only.
    """
    path = Path(path)
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

_ROLE = (
    "You are a senior structural analyst setting up Static Structural finite element runs in ANSYS "
    "Mechanical. You receive a compact JSON description of a part's geometry and a plain-English brief "
    "about the part's job. You return one complete SetupProposal: materials for every body, supports, "
    "loads, load cases, and mesh, each with a one-line rationale, plus the assumptions you made and the "
    "questions you would ask the engineer."
)

_UNITS = 'Units are fixed: {"length": "mm", "force": "N", "mass": "kg"}. Pressures are MPa. Accelerations are in g.'

_SCHEMA_NOTES = (
    "Output schema: SetupProposal. Targets are face ids (f12) or hole-group ids (hg1) taken only from the "
    "summary. Support types: fixed, frictionless, cylindrical, displacement. Load types: force, pressure, "
    "remote_force, bearing_load. Directions are unit vectors {x, y, z}. Every body needs exactly one material "
    "whose material_id exists in the database listed in the playbook. Return the whole proposal every time, "
    "including on revisions."
)


@dataclass
class ProposalResult:
    proposal: SetupProposal
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    latency_s: float


def load_playbook() -> str:
    return _PLAYBOOK_PATH.read_text(encoding="utf-8")


def playbook_hash() -> str:
    return hashlib.sha256(_PLAYBOOK_PATH.read_bytes()).hexdigest()[:12]


def build_system_prompt(playbook: str) -> list[dict]:
    text = "\n\n".join([_ROLE, _UNITS, _SCHEMA_NOTES, "# Playbook\n\n" + playbook])
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def build_user_message(summary: GeometrySummary, brief: str, prior: Optional[SetupProposal] = None,
                       feedback: Optional[list[str]] = None, instruction: Optional[str] = None) -> str:
    parts = ["GEOMETRY SUMMARY (JSON):", summary.model_dump_json(indent=1), "", "BRIEF:", brief.strip()]
    if prior is not None:
        parts += ["", "PRIOR PROPOSAL (JSON):", prior.model_dump_json(indent=1)]
    if feedback:
        parts += ["", "VALIDATOR MESSAGES (fix every one):"] + [f"- {m}" for m in feedback]
    if instruction:
        parts += ["", "ENGINEER'S INSTRUCTION:", instruction.strip()]
    return "\n".join(parts)


def _summary_hash(summary: GeometrySummary) -> str:
    return hashlib.sha256(summary.model_dump_json().encode("utf-8")).hexdigest()[:12]


def _default_client():
    import anthropic
    return anthropic.Anthropic()


def propose(summary: GeometrySummary, brief: str, playbook: Optional[str] = None,
            prior: Optional[SetupProposal] = None, feedback: Optional[list[str]] = None,
            instruction: Optional[str] = None, client=None, model: str = MODEL,
            session_id: str = "", log_path: Path = DEFAULT_LOG) -> ProposalResult:
    client = client or _default_client()
    playbook = playbook if playbook is not None else load_playbook()
    user = build_user_message(summary, brief, prior=prior, feedback=feedback, instruction=instruction)

    t0 = time.perf_counter()
    resp = client.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=build_system_prompt(playbook),
        messages=[{"role": "user", "content": user}],
        output_format=SetupProposal,
        thinking={"type": "adaptive"},
    )
    latency = time.perf_counter() - t0
    proposal: SetupProposal = resp.parsed_output
    usage = getattr(resp, "usage", None)
    result = ProposalResult(
        proposal=proposal,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        latency_s=round(latency, 3),
    )
    _log(result, summary, brief, model, session_id, log_path)
    return result


def _log(result: ProposalResult, summary: GeometrySummary, brief: str, model: str,
         session_id: str, log_path: Path) -> None:
    row = {
        "kind": "call",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cache_read_tokens": result.cache_read_tokens,
        "latency_s": result.latency_s,
        "playbook_hash": playbook_hash(),
        "brief": brief,
        "summary_hash": _summary_hash(summary),
        "proposal": result.proposal.model_dump(),
    }
    append_jsonl(log_path, row)
