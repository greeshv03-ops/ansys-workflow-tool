import io
import zipfile
import cadquery as cq
import pytest
from fastapi.testclient import TestClient
from src.agent.proposer import ProposalResult
from src.agent.schema import SetupProposal
import src.web.app as webapp


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture(scope="session")
def step_bytes(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "bracket.step"
    shape = cq.Workplane("XY").box(100, 50, 20).faces(">Z").workplane().hole(10)
    cq.exporters.export(shape, str(path))
    return path.read_bytes()


@pytest.fixture(scope="session")
def four_solid_step_bytes(tmp_path_factory):
    """Four separate boxes exported together, above the agent path's 3-solid limit."""
    path = tmp_path_factory.mktemp("cad") / "four_solids.step"
    parts = [cq.Workplane("XY").box(20, 20, 20).translate((40 * i, 0, 0)) for i in range(4)]
    assy = parts[0]
    for p in parts[1:]:
        assy = assy.add(p)
    cq.exporters.export(assy, str(path))
    return path.read_bytes()


def proposal_for(summary, bad=False):
    top = next(f.id for f in summary.faces if f.label.startswith("+Z"))
    bottom = next(f.id for f in summary.faces if f.label.startswith("-Z"))
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": bottom, "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": "f99" if bad else top, "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "mass"}],
        "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "g"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": ["a"], "questions": ["q"]})


@pytest.fixture
def client(tmp_path, monkeypatch):
    webapp.SESSIONS.clear()
    webapp.SESSION_STARTS.clear()
    monkeypatch.setattr(webapp, "LOG_PATH", tmp_path / "log.jsonl")
    calls = []

    def fake_propose(summary, brief, **kw):
        calls.append(kw)
        bad = brief.strip().lower().startswith("bad")
        return ProposalResult(proposal_for(summary, bad=bad), 10, 5, 0, 0.1)
    webapp.app.state.propose_fn = fake_propose
    c = TestClient(webapp.app)
    c.calls = calls
    return c


def upload(client, step_bytes, name="bracket.step"):
    return client.post("/session", files={"file": (name, step_bytes, "application/octet-stream")})


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_upload_creates_session_with_summary_and_render(client, step_bytes):
    r = upload(client, step_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] in webapp.SESSIONS
    assert body["summary"]["units"]["length"] == "mm"
    assert body["render_png_base64"].startswith("iVBOR")


def test_upload_rejects_non_step(client):
    r = client.post("/session", files={"file": ("part.obj", b"xyz", "application/octet-stream")})
    assert r.status_code == 400 and "STEP" in r.json()["detail"]


def test_upload_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(webapp, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/session", files={"file": ("big.step", b"0" * 11, "application/octet-stream")})
    assert r.status_code == 413


def test_upload_rejects_multi_solid_step(client, four_solid_step_bytes):
    r = upload(client, four_solid_step_bytes, name="four_solids.step")
    assert r.status_code == 400
    assert "solids" in r.json()["detail"]
    assert webapp.SESSIONS == {}


def test_propose_returns_valid_proposal_and_render(client, step_bytes):
    sid = upload(client, step_bytes).json()["session_id"]
    r = client.post(f"/session/{sid}/propose", json={"brief": "A steel bracket holding a 5 kg pump."})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True and body["messages"] == [] and body["attempts"] == 1
    assert body["proposal"]["supports"][0]["id"] == "s1"
    assert body["render_png_base64"].startswith("iVBOR")
    assert client.calls[0]["session_id"] == sid


def test_propose_invalid_twice_is_flagged(client, step_bytes):
    sid = upload(client, step_bytes).json()["session_id"]
    r = client.post(f"/session/{sid}/propose", json={"brief": "bad brief"})
    assert r.status_code == 200 and r.json()["valid"] is False and r.json()["attempts"] == 2
    assert any(m.startswith("rule2") for m in r.json()["messages"])
    d = client.get(f"/session/{sid}/download")
    assert d.status_code == 409


def test_revise_passes_prior_and_instruction(client, step_bytes):
    sid = upload(client, step_bytes).json()["session_id"]
    client.post(f"/session/{sid}/propose", json={"brief": "A steel bracket."})
    r = client.post(f"/session/{sid}/revise", json={"instruction": "use aluminum"})
    assert r.status_code == 200
    kw = client.calls[-1]
    assert kw["instruction"] == "use aluminum" and kw["prior"] is not None
    assert len(webapp.SESSIONS[sid].history) == 2


def test_revise_before_propose_is_409(client, step_bytes):
    sid = upload(client, step_bytes).json()["session_id"]
    assert client.post(f"/session/{sid}/revise", json={"instruction": "x"}).status_code == 409


def test_download_zip_has_journal_and_report(client, step_bytes):
    sid = upload(client, step_bytes).json()["session_id"]
    client.post(f"/session/{sid}/propose", json={"brief": "A steel bracket."})
    d = client.get(f"/session/{sid}/download")
    assert d.status_code == 200 and d.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(d.content))
    names = set(z.namelist())
    assert "simulation_setup.wbjn" in names and "settings_summary.html" in names
    assert b"Static Structural" in z.read("simulation_setup.wbjn")


def test_download_zip_ships_step_under_original_name(client, step_bytes):
    sid = upload(client, step_bytes, name="my part.step").json()["session_id"]
    sess = webapp.SESSIONS[sid]
    temp_path = sess.geometry_path
    client.post(f"/session/{sid}/propose", json={"brief": "A steel bracket."})
    d = client.get(f"/session/{sid}/download")
    assert d.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(d.content))
    names = set(z.namelist())
    assert "my part.step" in names
    assert z.read("my part.step") == step_bytes
    assert "README.txt" in names
    journal_text = z.read("simulation_setup.wbjn").decode("utf-8")
    assert "my part.step" in journal_text
    assert temp_path not in journal_text


def test_calls_per_session_cap(client, step_bytes, monkeypatch):
    monkeypatch.setattr(webapp, "CALLS_PER_SESSION", 2)
    sid = upload(client, step_bytes).json()["session_id"]
    assert client.post(f"/session/{sid}/propose", json={"brief": "A"}).status_code == 200
    assert client.post(f"/session/{sid}/revise", json={"instruction": "b"}).status_code == 200
    r = client.post(f"/session/{sid}/revise", json={"instruction": "c"})
    assert r.status_code == 429 and "2" in r.json()["detail"]


def test_repropose_failure_keeps_prior_valid_proposal(client, step_bytes, monkeypatch):
    sid = upload(client, step_bytes).json()["session_id"]
    r = client.post(f"/session/{sid}/propose", json={"brief": "A steel bracket."})
    assert r.status_code == 200 and r.json()["valid"] is True

    monkeypatch.setattr(webapp, "CALLS_PER_SESSION", 1)
    r2 = client.post(f"/session/{sid}/propose", json={"brief": "Another steel bracket."})
    assert r2.status_code == 429

    sess = webapp.SESSIONS[sid]
    assert sess.proposal is not None and sess.valid is True
    d = client.get(f"/session/{sid}/download")
    assert d.status_code == 200


def test_sessions_per_hour_cap(client, step_bytes, monkeypatch):
    monkeypatch.setattr(webapp, "SESSION_CAP_PER_HOUR", 1)
    assert upload(client, step_bytes).status_code == 200
    assert upload(client, step_bytes).status_code == 429


def test_expired_session_is_404(client, step_bytes, monkeypatch):
    sid = upload(client, step_bytes).json()["session_id"]
    webapp.SESSIONS[sid].last_used -= webapp.SESSION_TTL_S + 1
    r = client.post(f"/session/{sid}/propose", json={"brief": "A"})
    assert r.status_code == 404 and sid not in webapp.SESSIONS


def test_unknown_session_is_404(client):
    assert client.post("/session/nope/propose", json={"brief": "A"}).status_code == 404
