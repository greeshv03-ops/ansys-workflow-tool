"""Resilience of the eval runner and the proposer's client against transient call failures."""
import functools

import pytest

import evals.run_evals as run_evals
from src.agent.pipeline import run_pipeline
from src.agent.proposer import ProposalResult, _default_client
from src.agent.schema import SetupProposal


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


def proposal_for(summary):
    top = next(f.id for f in summary.faces if f.label.startswith("+Z"))
    bottom = next(f.id for f in summary.faces if f.label.startswith("-Z"))
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": bottom, "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": top, "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "mass"}],
        "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "g"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": ["a"], "questions": ["q"]})


@pytest.fixture
def isolated_runner(tmp_path, monkeypatch):
    """Keep the runner's log and results out of the repo during tests."""
    monkeypatch.setattr(run_evals, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(run_evals, "run_pipeline", functools.partial(run_pipeline, log_path=tmp_path / "log.jsonl"))
    return tmp_path


def test_run_retries_a_failed_call_once_and_continues(isolated_runner):
    calls = []

    def flaky_propose(summary, brief, **kw):
        calls.append(kw["session_id"])
        if len(calls) == 1:
            raise RuntimeError("Connection error.")
        return ProposalResult(proposal_for(summary), 10, 5, 0, 0.1)

    table = run_evals.run(["bracket_l_4hole"], repeats=2, propose_fn=flaky_propose, retry_wait_s=0)

    assert len(calls) == 3, "first run failed once and was retried, second run succeeded"
    row = next(l for l in table.splitlines() if l.startswith("| bracket_l_4hole |"))
    assert "1.00" in row and "failed" not in row
    assert list((isolated_runner / "results").glob("*.md")), "results file is still written"


def test_run_records_a_run_that_fails_twice_and_still_writes_results(isolated_runner):
    def dead_propose(summary, brief, **kw):
        raise RuntimeError("Connection error.")

    table = run_evals.run(["bracket_l_4hole"], repeats=2, propose_fn=dead_propose, retry_wait_s=0)

    row = next(l for l in table.splitlines() if l.startswith("| bracket_l_4hole"))
    assert "failed 2/2" in row and "—" in row
    assert list((isolated_runner / "results").glob("*.md")), "results file is written even when every run failed"


def test_default_client_retries_more_than_the_sdk_default(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert _default_client().max_retries >= 4
