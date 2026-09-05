"""propose → validate → at most one revision call. No third attempt."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.agent.proposer import DEFAULT_LOG, ProposalResult, append_jsonl, propose
from src.agent.schema import GeometrySummary, SetupProposal
from src.agent.validator import validate
from src.materials.database import MaterialDatabase

MAX_ATTEMPTS = 2


@dataclass
class PipelineResult:
    proposal: SetupProposal
    messages: list[str]
    attempts: int
    valid: bool
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})


def run_pipeline(summary: GeometrySummary, brief: str, db: MaterialDatabase,
                 prior: Optional[SetupProposal] = None, instruction: Optional[str] = None,
                 session_id: str = "", propose_fn: Callable[..., ProposalResult] = propose,
                 log_path: Path = DEFAULT_LOG) -> PipelineResult:
    tokens = {"input": 0, "output": 0, "cache_read": 0}
    feedback: Optional[list[str]] = None
    current_prior = prior
    result: Optional[ProposalResult] = None
    messages: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = propose_fn(summary, brief, prior=current_prior, feedback=feedback,
                            instruction=instruction, session_id=session_id, log_path=log_path)
        tokens["input"] += result.input_tokens
        tokens["output"] += result.output_tokens
        tokens["cache_read"] += result.cache_read_tokens
        messages = validate(result.proposal, summary, db)
        append_validator_outcome(log_path, session_id, messages)
        if not messages:
            return PipelineResult(result.proposal, [], attempt, True, tokens)
        current_prior = result.proposal
        feedback = messages
        instruction = None  # the instruction was already applied on the first attempt

    return PipelineResult(result.proposal, messages, MAX_ATTEMPTS, False, tokens)


def append_validator_outcome(log_path: Path, session_id: str, messages: list[str]) -> None:
    """Append a new validator-outcome row for this session.

    The log is append-only (see src.agent.proposer.append_jsonl): rather than
    reading the whole file, mutating the matching call row, and rewriting it
    (which truncates the file and loses any row appended concurrently by
    another session's request), each validator outcome is its own row,
    correlated to its call by session_id.
    """
    row = {
        "kind": "validator",
        "session_id": session_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "validator": {"valid": not messages, "messages": list(messages)},
    }
    append_jsonl(log_path, row)
