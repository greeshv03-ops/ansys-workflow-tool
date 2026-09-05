import json
import pytest
from src.agent.pipeline import run_pipeline, PipelineResult
from src.agent.proposer import ProposalResult
from src.agent.schema import SetupProposal, GeometrySummary
from src.materials.database import MaterialDatabase


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"}, "bbox_mm": vec(100, 50, 20),
        "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [
            {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"},
            {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, -10), "normal": vec(0, 0, -1), "radius_mm": None, "label": "-Z face (bottom)"},
            {"id": "f2", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(50, 0, 0), "normal": vec(1, 0, 0), "radius_mm": None, "label": "+X face (right)"}],
        "hole_groups": [], "symmetry_planes": [], "thin_walls": False})


def make_proposal(target="f2", magnitude=500.0):
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": "f1", "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": target, "type": "force", "magnitude": magnitude, "direction": vec(0, 0, -1), "rationale": "mass"}],
        "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "g"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": [], "questions": []})


def scripted(*proposals):
    """propose_fn that returns the given proposals in order and records its calls."""
    calls = []
    queue = list(proposals)

    def fn(summary, brief, **kw):
        calls.append(kw)
        p = queue.pop(0)
        return ProposalResult(proposal=p, input_tokens=10, output_tokens=5, cache_read_tokens=0, latency_s=0.1)
    fn.calls = calls
    return fn


def test_valid_first_try(summary, tmp_path):
    fn = scripted(make_proposal())
    r = run_pipeline(summary, "brief", MaterialDatabase(), propose_fn=fn, log_path=tmp_path / "l.jsonl")
    assert isinstance(r, PipelineResult) and r.valid and r.attempts == 1 and r.messages == []
    assert r.tokens == {"input": 10, "output": 5, "cache_read": 0}


def test_invalid_then_valid_retries_once_with_feedback(summary, tmp_path):
    fn = scripted(make_proposal(target="f99"), make_proposal())
    r = run_pipeline(summary, "brief", MaterialDatabase(), propose_fn=fn, log_path=tmp_path / "l.jsonl")
    assert r.valid and r.attempts == 2
    second = fn.calls[1]
    assert second["prior"].loads[0].target == "f99"
    assert any(m.startswith("rule2") for m in second["feedback"])
    assert r.tokens == {"input": 20, "output": 10, "cache_read": 0}


def test_invalid_twice_returns_flagged_without_third_call(summary, tmp_path):
    fn = scripted(make_proposal(target="f99"), make_proposal(target="f98"))
    r = run_pipeline(summary, "brief", MaterialDatabase(), propose_fn=fn, log_path=tmp_path / "l.jsonl")
    assert not r.valid and r.attempts == 2 and len(fn.calls) == 2
    assert any("f98" in m for m in r.messages)


def test_revision_passes_prior_and_instruction(summary, tmp_path):
    fn = scripted(make_proposal())
    prior = make_proposal(magnitude=100.0)
    run_pipeline(summary, "brief", MaterialDatabase(), prior=prior, instruction="double the load",
                 propose_fn=fn, log_path=tmp_path / "l.jsonl")
    kw = fn.calls[0]
    assert kw["prior"] is prior and kw["instruction"] == "double the load" and kw["feedback"] is None


def test_validator_outcome_appends_a_new_row(tmp_path):
    from src.agent.pipeline import append_validator_outcome
    log = tmp_path / "l.jsonl"
    log.write_text(json.dumps({"kind": "call", "session_id": "s"}) + "\n")
    append_validator_outcome(log, "s", ["rule2: x"])
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 2
    validator_row = rows[-1]
    assert validator_row["kind"] == "validator"
    assert validator_row["session_id"] == "s"
    assert validator_row["validator"] == {"valid": False, "messages": ["rule2: x"]}
    # the original call row survives untouched
    assert rows[0] == {"kind": "call", "session_id": "s"}


def test_interleaved_sessions_produce_four_rows_with_correct_session_ids(tmp_path):
    from src.agent.proposer import append_jsonl
    from src.agent.pipeline import append_validator_outcome
    log = tmp_path / "l.jsonl"
    # A call, B call, A outcome, B outcome
    append_jsonl(log, {"kind": "call", "session_id": "A"})
    append_jsonl(log, {"kind": "call", "session_id": "B"})
    append_validator_outcome(log, "A", [])
    append_validator_outcome(log, "B", ["rule2: x"])
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 4
    validator_rows = [r for r in rows if r["kind"] == "validator"]
    assert len(validator_rows) == 2
    a_outcome = next(r for r in validator_rows if r["session_id"] == "A")
    b_outcome = next(r for r in validator_rows if r["session_id"] == "B")
    assert a_outcome["validator"] == {"valid": True, "messages": []}
    assert b_outcome["validator"] == {"valid": False, "messages": ["rule2: x"]}


def test_append_jsonl_is_safe_under_thread_contention(tmp_path):
    import threading
    from src.agent.proposer import append_jsonl
    log = tmp_path / "concurrent.jsonl"
    n = 20

    def worker(i):
        append_jsonl(log, {"kind": "call", "session_id": str(i)})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n
    rows = [json.loads(line) for line in lines]  # every row parses cleanly: no interleaved writes
    assert sorted(int(r["session_id"]) for r in rows) == list(range(n))
