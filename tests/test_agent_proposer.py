# tests/test_agent_proposer.py
import json
import os
from types import SimpleNamespace
import pytest
from src.agent.proposer import (build_system_prompt, build_user_message, load_playbook,
                                playbook_hash, propose, MODEL, MAX_TOKENS)
from src.agent.schema import SetupProposal, GeometrySummary


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"}, "bbox_mm": vec(100, 50, 20),
        "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [{"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10),
                   "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"}],
        "hole_groups": [], "symmetry_planes": [], "thin_walls": False})


@pytest.fixture
def proposal():
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": "f0", "type": "fixed", "rationale": "x"}],
        "loads": [], "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": [], "support_ids": ["s1"], "rationale": "g"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": [], "questions": []})


class FakeMessages:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.proposal,
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=900))


def fake_client(proposal):
    return SimpleNamespace(messages=FakeMessages(proposal))


def test_playbook_loads_and_hashes():
    text = load_playbook()
    assert "Support selection" in text
    assert len(playbook_hash()) == 12


def test_system_prompt_is_cached_block():
    blocks = build_system_prompt("PLAYBOOK TEXT")
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    joined = " ".join(b["text"] for b in blocks)
    assert "PLAYBOOK TEXT" in joined and '"length": "mm"' in joined and "SetupProposal" in joined


def test_user_message_contains_summary_and_brief(summary):
    msg = build_user_message(summary, "A steel bracket holding a 5 kg pump.")
    assert '"id": "f0"' in msg and "5 kg pump" in msg
    assert "PRIOR PROPOSAL" not in msg


def test_user_message_revision_sections(summary, proposal):
    msg = build_user_message(summary, "brief", prior=proposal, feedback=["rule2: bad"], instruction="use aluminum")
    assert "PRIOR PROPOSAL" in msg and "rule2: bad" in msg and "use aluminum" in msg


def test_propose_calls_parse_with_schema_and_thinking(summary, proposal, tmp_path):
    client = fake_client(proposal)
    result = propose(summary, "brief", client=client, log_path=tmp_path / "log.jsonl")
    kw = client.messages.calls[0]
    assert kw["model"] == MODEL and kw["max_tokens"] == MAX_TOKENS
    assert kw["output_format"] is SetupProposal
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["messages"][0]["role"] == "user"
    assert result.proposal == proposal
    assert result.input_tokens == 1200 and result.cache_read_tokens == 900


def test_propose_logs_jsonl(summary, proposal, tmp_path):
    log = tmp_path / "log.jsonl"
    propose(summary, "brief", client=fake_client(proposal), session_id="abc", log_path=log)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    for key in ("kind", "timestamp", "session_id", "model", "input_tokens", "output_tokens", "cache_read_tokens",
                "latency_s", "playbook_hash", "brief", "summary_hash", "proposal"):
        assert key in row
    assert row["kind"] == "call"
    assert row["session_id"] == "abc" and row["proposal"]["materials"][0]["material_id"] == 1


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="live smoke test needs ANTHROPIC_API_KEY")
def test_live_smoke(summary, tmp_path):
    result = propose(summary, "A mild steel bracket bolted through its top face, carrying a 2 kg sensor.",
                     log_path=tmp_path / "log.jsonl")
    assert result.proposal.supports and result.proposal.load_cases
