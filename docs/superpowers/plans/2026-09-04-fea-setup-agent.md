# FEA Setup Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI web app that takes a STEP file plus a plain-English brief, asks Claude for a complete Static Structural setup as structured JSON, validates it deterministically, renders the chosen faces, writes the ANSYS journal and report, and scores itself against ten reference parts.

**Architecture:** New `src/agent/` package (schema, summary builder, validator, adapter, proposer, pipeline, renderer) reuses the existing `GeometryAnalyzer`, `MaterialDatabase`, `JournalGenerator`, and `SummaryGenerator`. The adapter produces one `SimulationConfig` carrying a new optional `load_cases` list; the static journal template loops over it to emit one Workbench system per load case. A `src/web/` FastAPI app with a single static HTML page fronts the pipeline. `evals/` holds cadquery-generated parts, hand-written references, and a scorer.

**Tech Stack:** Python 3.11, Pydantic v2, Anthropic Python SDK (`client.messages.parse` with `output_format=SetupProposal`, `thinking={"type": "adaptive"}`), FastAPI + uvicorn, cadquery 2.7, pyvista 0.48 off-screen, Jinja2, pytest, Docker (micromamba).

**Spec:** `docs/superpowers/specs/2026-09-03-fea-setup-agent-design.md`

## Global Constraints

- Python `>=3.11` (pyproject). Existing 46 tests must keep passing after every task: `python -m pytest -q`.
- Sim type: Static Structural only. STEP input only on the agent path.
- Units in every prompt and summary: `{"length": "mm", "force": "N", "mass": "kg"}`. Accelerations in g; 1 g = 9806.65 mm/s².
- Model id: `claude-opus-5`. `max_tokens=16000`. Adaptive thinking on. API key from `ANTHROPIC_API_KEY` only.
- Summary caps: prune faces below 0.1 percent of total surface area unless in a hole group; hard cap 200 faces; upload cap 20 MB.
- Validator retry: exactly one automatic revision call, never a third.
- Session caps: 10 proposal/revision calls per session, 50 sessions per hour per process, one-hour session expiry. Env overrides `SESSION_CAP_PER_HOUR`, `CALLS_PER_SESSION`.
- Render: isometric, 1200 by 900 PNG, supports blue `#3F6F9E`, loads orange `#D98A2B`, other faces `#D0D4D8`.
- Every model call appends one JSON line to `logs/proposals.jsonl`.
- Two deviations from the spec, both deliberate: (1) direction and acceleration vectors are a `Vec3{x,y,z}` object rather than a tuple, because structured-output JSON schema does not accept `prefixItems`; (2) the adapter returns one `SimulationConfig` with a `load_cases` list rather than one config per load case, so the existing generators run unchanged and the journal loop has everything in one object.
- Commit after every task with the message shown. Do not amend.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/agent/__init__.py` | empty |
| `src/agent/schema.py` | Pydantic models: `Vec3`, `SetupProposal` tree, `GeometrySummary` tree |
| `src/agent/summary.py` | `build_summary(features, bodies) -> GeometrySummary`; hole grouping, pruning, cap |
| `src/agent/validator.py` | `validate(proposal, summary, db) -> list[str]`; eight rules |
| `src/agent/adapter.py` | `to_config(proposal, summary, features, geometry_path, db) -> SimulationConfig` |
| `src/agent/playbook.md` | engineering reference loaded into the system prompt |
| `src/agent/proposer.py` | `propose(...) -> ProposalResult`; JSONL logging |
| `src/agent/pipeline.py` | `run_pipeline(...) -> PipelineResult`; validate, retry once |
| `src/agent/render.py` | `render_image(...) -> ndarray`, `render_png(...) -> bytes` |
| `src/web/app.py` | FastAPI app, sessions, caps, endpoints |
| `src/web/static/index.html` | the one-page UI |
| `src/models.py` | modify: `FaceLabel.axis/axis_point/index`, `BoundaryCondition.rationale`, `BodyMaterial.rationale`, new `LoadCaseBlock`, `SimulationConfig.load_cases/assumptions/questions` |
| `src/geometry/analyzer.py` | modify: record cylinder axis and face index in `_label_faces` |
| `src/generator/journal.py` | modify: pass `load_cases` to the template |
| `src/generator/templates/static_structural.wbjn.j2` | modify: loop over load cases |
| `src/generator/templates/settings_summary.html.j2` | modify: load-case table, rationale column, assumptions, questions |
| `evals/make_parts.py` | cadquery scripts that write the ten STEP parts |
| `evals/parts/<name>/{part.step,brief.md,reference.json}` | eval set |
| `evals/run_evals.py` | scorer, runner, markdown results writer |
| `Dockerfile`, `README.md`, `requirements.txt` | deployment and docs |

---

### Task 1: Proposal and Summary Schemas

**Files:**
- Create: `src/agent/__init__.py` (empty)
- Create: `src/agent/schema.py`
- Test: `tests/test_agent_schema.py`
- Modify: `requirements.txt` (add `pydantic>=2.7`)

**Interfaces:**
- Consumes: nothing.
- Produces: `Vec3(x, y, z)` with `.as_tuple() -> tuple[float,float,float]` and `.length() -> float`; `MaterialAssignment`, `Support`, `Load`, `LoadCase`, `Refinement`, `MeshProposal`, `SetupProposal`; `SummaryBody`, `SummaryFace`, `HoleGroup`, `GeometrySummary`. All are Pydantic v2 `BaseModel` with `extra="forbid"`.

- [ ] **Step 1: Install pydantic and record it**

Run: `pip install "pydantic>=2.7"` then append `pydantic>=2.7` to `requirements.txt`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_agent_schema.py
import json
import pytest
from pydantic import ValidationError
from src.agent.schema import SetupProposal, GeometrySummary, Vec3


def proposal_dict():
    return {
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel bracket"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted to frame"}],
        "loads": [{"id": "l1", "target": "f2", "type": "force", "magnitude": 500.0,
                   "direction": {"x": 0, "y": 0, "z": -1}, "rationale": "hanging mass"}],
        "load_cases": [{"name": "static 1g", "acceleration_g": {"x": 0, "y": 0, "z": -1},
                        "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity only"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid",
                 "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "bolt holes"}]},
        "assumptions": ["mass hangs from the free end"],
        "questions": ["what is the bolt preload?"],
    }


def summary_dict():
    return {
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": {"x": 100, "y": 50, "z": 20},
        "volume_mm3": 100000.0,
        "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0,
                    "centroid_mm": {"x": 0, "y": 0, "z": 0}, "bbox_mm": {"x": 100, "y": 50, "z": 20}}],
        "faces": [{"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000.0,
                   "centroid_mm": {"x": 0, "y": 0, "z": 10}, "normal": {"x": 0, "y": 0, "z": 1},
                   "radius_mm": None, "label": "+Z face (top, 5000 mm²)"}],
        "hole_groups": [],
        "symmetry_planes": ["XY"],
        "thin_walls": False,
    }


def test_proposal_round_trip():
    p = SetupProposal.model_validate(proposal_dict())
    assert p.loads[0].direction.as_tuple() == (0.0, 0.0, -1.0)
    assert SetupProposal.model_validate_json(p.model_dump_json()) == p


def test_vec3_length():
    assert abs(Vec3(x=3, y=4, z=0).length() - 5.0) < 1e-9


def test_proposal_rejects_unknown_support_type():
    d = proposal_dict()
    d["supports"][0]["type"] = "glued"
    with pytest.raises(ValidationError):
        SetupProposal.model_validate(d)


def test_proposal_rejects_extra_fields():
    d = proposal_dict()
    d["extra"] = 1
    with pytest.raises(ValidationError):
        SetupProposal.model_validate(d)


def test_proposal_schema_has_no_tuple_constructs():
    schema = json.dumps(SetupProposal.model_json_schema())
    assert "prefixItems" not in schema


def test_summary_round_trip():
    s = GeometrySummary.model_validate(summary_dict())
    assert s.faces[0].id == "f0"
    assert s.face_by_id("f0").label.startswith("+Z")
    assert s.face_by_id("nope") is None


def test_summary_target_face_ids_expands_hole_groups():
    d = summary_dict()
    d["faces"].append({"id": "f1", "body_id": 0, "type": "cylindrical", "area_mm2": 300.0,
                       "centroid_mm": {"x": 10, "y": 10, "z": 0}, "normal": None,
                       "radius_mm": 4.0, "label": "Cyl hole #1"})
    d["hole_groups"] = [{"id": "hg1", "face_ids": ["f1"], "radius_mm": 4.0, "count": 1,
                         "plane_normal": {"x": 0, "y": 0, "z": 1}, "pattern": "irregular"}]
    s = GeometrySummary.model_validate(d)
    assert s.target_face_ids("hg1") == ["f1"]
    assert s.target_face_ids("f0") == ["f0"]
    assert s.target_face_ids("zzz") == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_schema.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent'`

- [ ] **Step 4: Write the schema module**

```python
# src/agent/schema.py
"""Pydantic models shared by the proposal agent, validator, adapter, and web app.

Vectors are objects, not tuples: structured-output JSON schema rejects prefixItems.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vec3(_Strict):
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


# ---------------------------------------------------------------- proposal

class MaterialAssignment(_Strict):
    body_id: int
    material_id: int = Field(description="Must exist in the materials database")
    rationale: str


class Support(_Strict):
    id: str = Field(description="s1, s2, ...")
    target: str = Field(description="face id (f12) or hole-group id (hg1)")
    type: Literal["fixed", "frictionless", "cylindrical", "displacement"]
    rationale: str


class Load(_Strict):
    id: str = Field(description="l1, l2, ...")
    target: str = Field(description="face id (f12) or hole-group id (hg1)")
    type: Literal["force", "pressure", "remote_force", "bearing_load"]
    magnitude: float = Field(description="N for force types, MPa for pressure")
    direction: Vec3 = Field(description="unit vector in the summary axes")
    rationale: str


class LoadCase(_Strict):
    name: str
    acceleration_g: Vec3 = Field(description="body acceleration in g, summary axes")
    load_ids: list[str]
    support_ids: list[str]
    rationale: str


class Refinement(_Strict):
    target: str
    size_mm: float
    reason: str


class MeshProposal(_Strict):
    global_size_mm: float
    element_type: Literal["Solid", "Shell", "Auto"]
    refinement: list[Refinement]


class SetupProposal(_Strict):
    materials: list[MaterialAssignment]
    supports: list[Support]
    loads: list[Load]
    load_cases: list[LoadCase]
    mesh: MeshProposal
    assumptions: list[str]
    questions: list[str]


# ----------------------------------------------------------------- summary

class SummaryBody(_Strict):
    id: int
    name: str
    volume_mm3: float
    centroid_mm: Vec3
    bbox_mm: Vec3


class SummaryFace(_Strict):
    id: str
    body_id: int
    type: Literal["planar", "cylindrical", "other"]
    area_mm2: float
    centroid_mm: Vec3
    normal: Optional[Vec3] = None
    radius_mm: Optional[float] = None
    label: str


class HoleGroup(_Strict):
    id: str
    face_ids: list[str]
    radius_mm: float
    count: int
    plane_normal: Vec3
    pattern: Literal["linear", "rectangular", "circular", "irregular"]


class GeometrySummary(_Strict):
    units: dict[str, str]
    bbox_mm: Vec3
    volume_mm3: float
    estimated_mass_kg: float
    bodies: list[SummaryBody]
    faces: list[SummaryFace]
    hole_groups: list[HoleGroup]
    symmetry_planes: list[str]
    thin_walls: bool

    def face_by_id(self, face_id: str) -> Optional[SummaryFace]:
        for f in self.faces:
            if f.id == face_id:
                return f
        return None

    def hole_group_by_id(self, group_id: str) -> Optional[HoleGroup]:
        for g in self.hole_groups:
            if g.id == group_id:
                return g
        return None

    def target_face_ids(self, target: str) -> list[str]:
        """Resolve a proposal target to face ids. Unknown targets give []."""
        g = self.hole_group_by_id(target)
        if g is not None:
            return list(g.face_ids)
        return [target] if self.face_by_id(target) is not None else []

    def target_exists(self, target: str) -> bool:
        return bool(self.target_face_ids(target))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_schema.py -q`
Expected: 7 passed

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q` → 53 passed

```bash
git add src/agent/__init__.py src/agent/schema.py tests/test_agent_schema.py requirements.txt
git commit -m "feat(agent): proposal and geometry summary schemas"
```

### Task 2: Validator

**Files:**
- Create: `src/agent/validator.py`
- Test: `tests/test_agent_validator.py`

**Interfaces:**
- Consumes: `SetupProposal`, `GeometrySummary` from Task 1; `MaterialDatabase.get_by_id(id) -> dict | None` with keys `name`, `category`, `yield_MPa` from `src/materials/database.py`.
- Produces: `validate(proposal: SetupProposal, summary: GeometrySummary, db: MaterialDatabase) -> list[str]`. Empty list means valid. Every message starts with `rule<N>:`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_validator.py
import pytest
from src.agent.schema import SetupProposal, GeometrySummary
from src.agent.validator import validate
from src.materials.database import MaterialDatabase


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    # One 100 x 50 x 20 box body, six planar faces + two hole faces in one group.
    faces = [
        {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"},
        {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, -10), "normal": vec(0, 0, -1), "radius_mm": None, "label": "-Z face (bottom)"},
        {"id": "f2", "body_id": 0, "type": "planar", "area_mm2": 2000, "centroid_mm": vec(0, 25, 0), "normal": vec(0, 1, 0), "radius_mm": None, "label": "+Y face (front)"},
        {"id": "f3", "body_id": 0, "type": "planar", "area_mm2": 2000, "centroid_mm": vec(0, -25, 0), "normal": vec(0, -1, 0), "radius_mm": None, "label": "-Y face (back)"},
        {"id": "f4", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(50, 0, 0), "normal": vec(1, 0, 0), "radius_mm": None, "label": "+X face (right)"},
        {"id": "f5", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(-50, 0, 0), "normal": vec(-1, 0, 0), "radius_mm": None, "label": "-X face (left)"},
        {"id": "f6", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 0, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
        {"id": "f7", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 15, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"},
    ]
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": vec(100, 50, 20), "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": faces,
        "hole_groups": [{"id": "hg1", "face_ids": ["f6", "f7"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False,
    })


def good_proposal():
    return {
        "materials": [{"body_id": 0, "material_id": 1, "rationale": "steel"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": "f4", "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "load"}],
        "load_cases": [{"name": "1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity"}],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "holes"}]},
        "assumptions": [], "questions": [],
    }


@pytest.fixture
def db():
    return MaterialDatabase()


def run(d, summary, db):
    return validate(SetupProposal.model_validate(d), summary, db)


def test_good_proposal_is_valid(summary, db):
    assert run(good_proposal(), summary, db) == []


def test_rule1_body_without_material(summary, db):
    d = good_proposal(); d["materials"] = []
    msgs = run(d, summary, db)
    assert any(m.startswith("rule1") and "body 0" in m for m in msgs)


def test_rule1_unknown_material_id(summary, db):
    d = good_proposal(); d["materials"][0]["material_id"] = 9999
    assert any(m.startswith("rule1") and "9999" in m for m in run(d, summary, db))


def test_rule1_duplicate_material_for_body(summary, db):
    d = good_proposal(); d["materials"].append({"body_id": 0, "material_id": 5, "rationale": "x"})
    assert any(m.startswith("rule1") and "exactly one" in m for m in run(d, summary, db))


def test_rule2_no_supports(summary, db):
    d = good_proposal(); d["supports"] = []; d["load_cases"][0]["support_ids"] = []
    assert any(m.startswith("rule2") and "at least one support" in m for m in run(d, summary, db))


def test_rule2_unknown_target(summary, db):
    d = good_proposal(); d["loads"][0]["target"] = "f99"
    assert any(m.startswith("rule2") and "f99" in m for m in run(d, summary, db))


def test_rule3_support_and_load_share_target(summary, db):
    d = good_proposal(); d["loads"][0]["target"] = "hg1"
    assert any(m.startswith("rule3") and "hg1" in m for m in run(d, summary, db))


def test_rule4_unknown_load_id(summary, db):
    d = good_proposal(); d["load_cases"][0]["load_ids"] = ["l9"]
    assert any(m.startswith("rule4") and "l9" in m for m in run(d, summary, db))


def test_rule4_empty_load_case(summary, db):
    d = good_proposal(); d["load_cases"][0]["load_ids"] = []; d["load_cases"][0]["acceleration_g"] = vec(0, 0, 0)
    assert any(m.startswith("rule4") and "no loads" in m for m in run(d, summary, db))


def test_rule4_unknown_support_id(summary, db):
    d = good_proposal(); d["load_cases"][0]["support_ids"] = ["s9"]
    assert any(m.startswith("rule4") and "s9" in m for m in run(d, summary, db))


def test_rule5_acceleration_too_high(summary, db):
    d = good_proposal(); d["load_cases"][0]["acceleration_g"] = vec(0, 0, -31)
    assert any(m.startswith("rule5") and "30 g" in m for m in run(d, summary, db))


def test_rule5_force_too_high(summary, db):
    d = good_proposal(); d["loads"][0]["magnitude"] = 2e6
    assert any(m.startswith("rule5") and "1e6" in m for m in run(d, summary, db))


def test_rule5_pressure_above_yield(summary, db):
    d = good_proposal(); d["loads"][0]["type"] = "pressure"; d["loads"][0]["magnitude"] = 400.0  # steel yield 250 MPa
    assert any(m.startswith("rule5") and "yield" in m for m in run(d, summary, db))


def test_rule6_global_size_out_of_band(summary, db):
    d = good_proposal(); d["mesh"]["global_size_mm"] = 0.5  # band is 1..10 for bbox max 100
    assert any(m.startswith("rule6") and "global" in m for m in run(d, summary, db))


def test_rule6_refinement_not_smaller(summary, db):
    d = good_proposal(); d["mesh"]["refinement"][0]["size_mm"] = 4.0
    assert any(m.startswith("rule6") and "refinement" in m for m in run(d, summary, db))


def test_rule7_fixed_covers_every_face(summary, db):
    d = good_proposal()
    d["supports"] = [{"id": f"s{i}", "target": f"f{i}", "type": "fixed", "rationale": "x"} for i in range(8)]
    d["loads"] = []; d["load_cases"][0]["load_ids"] = []; d["load_cases"][0]["support_ids"] = ["s0"]
    d["mesh"]["refinement"] = []
    assert any(m.startswith("rule7") and "every face" in m for m in run(d, summary, db))


def test_rule7_fixed_area_over_half(summary, db):
    d = good_proposal()
    d["supports"] = [{"id": "s1", "target": "f0", "type": "fixed", "rationale": "x"},
                     {"id": "s2", "target": "f1", "type": "fixed", "rationale": "x"}]  # 10000 of 16500 mm²
    assert any(m.startswith("rule7") and "50 percent" in m for m in run(d, summary, db))


def test_rule8_direction_not_unit(summary, db):
    d = good_proposal(); d["loads"][0]["direction"] = vec(0, 0, -2)
    assert any(m.startswith("rule8") and "l1" in m for m in run(d, summary, db))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_validator.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent.validator'`

- [ ] **Step 3: Write the validator**

```python
# src/agent/validator.py
"""Deterministic checks on a SetupProposal. Returns messages; empty means valid."""
from __future__ import annotations

from src.agent.schema import GeometrySummary, SetupProposal
from src.materials.database import MaterialDatabase

MAX_ACCEL_G = 30.0
MAX_FORCE_N = 1e6
GLOBAL_SIZE_MIN_FRACTION = 0.01
GLOBAL_SIZE_MAX_FRACTION = 0.10
FIXED_AREA_MAX_FRACTION = 0.50
UNIT_TOL = 0.01


def validate(proposal: SetupProposal, summary: GeometrySummary, db: MaterialDatabase) -> list[str]:
    msgs: list[str] = []
    msgs += _rule1_materials(proposal, summary, db)
    msgs += _rule2_targets(proposal, summary)
    msgs += _rule3_no_shared_targets(proposal)
    msgs += _rule4_load_cases(proposal)
    msgs += _rule5_magnitudes(proposal, summary, db)
    msgs += _rule6_mesh(proposal, summary)
    msgs += _rule7_overconstraint(proposal, summary)
    msgs += _rule8_unit_directions(proposal)
    return msgs


def _rule1_materials(p, s, db) -> list[str]:
    out = []
    counts: dict[int, int] = {}
    for m in p.materials:
        counts[m.body_id] = counts.get(m.body_id, 0) + 1
        if db.get_by_id(m.material_id) is None:
            out.append(f"rule1: material_id {m.material_id} for body {m.body_id} is not in the database")
    for b in s.bodies:
        n = counts.get(b.id, 0)
        if n == 0:
            out.append(f"rule1: body {b.id} ({b.name}) has no material assignment")
        elif n > 1:
            out.append(f"rule1: body {b.id} must have exactly one material assignment, found {n}")
    for body_id in counts:
        if s.body_by_id(body_id) is None:
            out.append(f"rule1: material assigned to unknown body {body_id}")
    return out


def _rule2_targets(p, s) -> list[str]:
    out = []
    if not p.supports:
        out.append("rule2: proposal needs at least one support")
    for sup in p.supports:
        if not s.target_exists(sup.target):
            out.append(f"rule2: support {sup.id} targets unknown face or hole group {sup.target}")
    for ld in p.loads:
        if not s.target_exists(ld.target):
            out.append(f"rule2: load {ld.id} targets unknown face or hole group {ld.target}")
    return out


def _rule3_no_shared_targets(p) -> list[str]:
    support_targets = {sup.target for sup in p.supports}
    return [f"rule3: target {ld.target} carries both a support and load {ld.id}"
            for ld in p.loads if ld.target in support_targets]


def _rule4_load_cases(p) -> list[str]:
    out = []
    load_ids = {ld.id for ld in p.loads}
    support_ids = {sup.id for sup in p.supports}
    for lc in p.load_cases:
        for lid in lc.load_ids:
            if lid not in load_ids:
                out.append(f"rule4: load case '{lc.name}' references unknown load id {lid}")
        for sid in lc.support_ids:
            if sid not in support_ids:
                out.append(f"rule4: load case '{lc.name}' references unknown support id {sid}")
        if not lc.load_ids and lc.acceleration_g.length() == 0.0:
            out.append(f"rule4: load case '{lc.name}' has no loads and zero acceleration")
    return out


def _rule5_magnitudes(p, s, db) -> list[str]:
    out = []
    for lc in p.load_cases:
        a = lc.acceleration_g
        if max(abs(a.x), abs(a.y), abs(a.z)) > MAX_ACCEL_G:
            out.append(f"rule5: load case '{lc.name}' acceleration exceeds 30 g")
    yield_by_body = {}
    for m in p.materials:
        row = db.get_by_id(m.material_id)
        if row and row.get("yield_MPa"):
            yield_by_body[m.body_id] = float(row["yield_MPa"])
    for ld in p.loads:
        if ld.type == "pressure":
            face_ids = s.target_face_ids(ld.target)
            body_id = s.face_by_id(face_ids[0]).body_id if face_ids else None
            y = yield_by_body.get(body_id)
            if y is not None and ld.magnitude >= y:
                out.append(f"rule5: load {ld.id} pressure {ld.magnitude:g} MPa is not below the material yield {y:g} MPa")
        elif abs(ld.magnitude) >= MAX_FORCE_N:
            out.append(f"rule5: load {ld.id} magnitude {ld.magnitude:g} N is not below 1e6 N")
    return out


def _rule6_mesh(p, s) -> list[str]:
    out = []
    largest = max(s.bbox_mm.as_tuple())
    lo, hi = largest * GLOBAL_SIZE_MIN_FRACTION, largest * GLOBAL_SIZE_MAX_FRACTION
    g = p.mesh.global_size_mm
    if not (lo <= g <= hi):
        out.append(f"rule6: mesh global size {g:g} mm is outside {lo:g} to {hi:g} mm (1 to 10 percent of {largest:g} mm)")
    for r in p.mesh.refinement:
        if r.size_mm >= g:
            out.append(f"rule6: refinement on {r.target} size {r.size_mm:g} mm is not smaller than the global size {g:g} mm")
    return out


def _rule7_overconstraint(p, s) -> list[str]:
    out = []
    fixed_faces: set[str] = set()
    for sup in p.supports:
        if sup.type == "fixed":
            fixed_faces.update(s.target_face_ids(sup.target))
    for b in s.bodies:
        body_faces = [f for f in s.faces if f.body_id == b.id]
        if not body_faces:
            continue
        body_fixed = [f for f in body_faces if f.id in fixed_faces]
        if len(body_fixed) == len(body_faces):
            out.append(f"rule7: fixed supports cover every face of body {b.id} ({b.name})")
            continue
        total = sum(f.area_mm2 for f in body_faces)
        fixed_area = sum(f.area_mm2 for f in body_fixed)
        if total > 0 and fixed_area / total >= FIXED_AREA_MAX_FRACTION:
            out.append(f"rule7: fixed support area on body {b.id} is {100 * fixed_area / total:.0f} percent of its surface, must be below 50 percent")
    return out


def _rule8_unit_directions(p) -> list[str]:
    return [f"rule8: load {ld.id} direction has length {ld.direction.length():.3f}, must be a unit vector"
            for ld in p.loads if abs(ld.direction.length() - 1.0) > UNIT_TOL]
```

Also add to `GeometrySummary` in `src/agent/schema.py`, next to `face_by_id`:

```python
    def body_by_id(self, body_id: int) -> Optional[SummaryBody]:
        for b in self.bodies:
            if b.id == body_id:
                return b
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_validator.py -q`
Expected: 18 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q` → 71 passed

```bash
git add src/agent/validator.py src/agent/schema.py tests/test_agent_validator.py
git commit -m "feat(agent): deterministic proposal validator with eight rules"
```

### Task 3: Summary Builder and Cylinder Axis Capture

**Files:**
- Modify: `src/models.py:18-25` (`FaceLabel` gains `axis`, `axis_point`, `index`)
- Modify: `src/geometry/analyzer.py:268-340` (`_label_faces` records the cylinder axis and the face index)
- Create: `src/agent/summary.py`
- Test: `tests/test_agent_summary.py`

**Interfaces:**
- Consumes: `GeometryFeatures`, `Body`, `FaceLabel` from `src/models.py`; `GeometryAnalyzer.analyze_with_solids(path)` from `src/geometry/analyzer.py`.
- Produces: `build_summary(features: GeometryFeatures, bodies: list[Body]) -> GeometrySummary`; raises `ValueError("Part has N labeled faces, above the cap of 200")`. Constants `FACE_CAP = 200`, `PRUNE_FRACTION = 0.001`. Face ids are `f{index}` where `index` is the position in `features.faces`; hole groups are `hg{n}` in first-seen order.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_summary.py
import cadquery as cq
import pytest
from src.agent.summary import build_summary, FACE_CAP
from src.geometry.analyzer import GeometryAnalyzer
from src.models import Body, FaceLabel, GeometryFeatures


@pytest.fixture(scope="session")
def plate_4holes_step(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "plate4.step"
    plate = (cq.Workplane("XY").box(100, 60, 10)
             .faces(">Z").workplane().rect(70, 40, forConstruction=True).vertices().hole(8))
    cq.exporters.export(plate, str(path))
    return str(path)


@pytest.fixture(scope="session")
def plate_2holes_step(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "plate2.step"
    plate = (cq.Workplane("XY").box(100, 30, 10)
             .faces(">Z").workplane().pushPoints([(-30, 0), (30, 0)]).hole(6))
    cq.exporters.export(plate, str(path))
    return str(path)


def test_analyzer_records_cylinder_axis(plate_2holes_step):
    features = GeometryAnalyzer.analyze(plate_2holes_step)
    cyl = [f for f in features.faces if f.face_type == "cylindrical"]
    assert cyl and all(f.axis is not None and f.axis_point is not None for f in cyl)
    assert abs(abs(cyl[0].axis[2]) - 1.0) < 1e-3


def test_analyzer_records_face_index(plate_2holes_step):
    features = GeometryAnalyzer.analyze(plate_2holes_step)
    assert sorted(f.index for f in features.faces) == list(range(len(features.faces)))


def test_summary_units_and_ids(plate_2holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_2holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert s.units == {"length": "mm", "force": "N", "mass": "kg"}
    assert [f.id for f in s.faces] == [f"f{i}" for i in range(len(s.faces))]
    assert s.faces[0].label == features.faces[0].name
    assert abs(s.estimated_mass_kg - features.volume * 1e-9 * 7850) < 1e-6


def test_hole_group_linear(plate_2holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_2holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert len(s.hole_groups) == 1
    g = s.hole_groups[0]
    assert g.id == "hg1" and g.count == 2 and g.pattern == "linear"
    assert abs(g.radius_mm - 3.0) < 0.05
    assert abs(abs(g.plane_normal.z) - 1.0) < 1e-3


def test_hole_group_rectangular(plate_4holes_step):
    features, solids = GeometryAnalyzer.analyze_with_solids(plate_4holes_step)
    s = build_summary(features, [ns.body for ns in solids])
    assert len(s.hole_groups) == 1
    assert s.hole_groups[0].count == 4
    assert s.hole_groups[0].pattern == "rectangular"


def _synthetic_features(n_faces: int, tiny: bool = False) -> GeometryFeatures:
    faces = [FaceLabel(name=f"face {i}", face_type="planar", area=100.0,
                       centroid=(0, 0, 0), normal=(0, 0, 1), index=i) for i in range(n_faces)]
    if tiny:
        faces.append(FaceLabel(name="speck", face_type="planar", area=0.01,
                               centroid=(1, 1, 1), normal=(0, 0, 1), index=n_faces))
    total = sum(f.area for f in faces)
    return GeometryFeatures(bbox=(100, 50, 20), volume=1000.0, surface_area=total, body_count=1,
                            thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False, faces=faces,
                            bodies=[Body(id=0, name="b", volume=1000.0, centroid=(0, 0, 0), bbox=(100, 50, 20))])


def test_prunes_tiny_faces():
    f = _synthetic_features(5, tiny=True)
    s = build_summary(f, f.bodies)
    assert all(face.label != "speck" for face in s.faces)
    assert len(s.faces) == 5


def test_face_cap_rejects_large_parts():
    f = _synthetic_features(FACE_CAP + 1)
    with pytest.raises(ValueError, match="above the cap"):
        build_summary(f, f.bodies)


def test_single_body_faces_get_body_zero():
    f = _synthetic_features(3)
    s = build_summary(f, f.bodies)
    assert {face.body_id for face in s.faces} == {0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_summary.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent.summary'` (and `TypeError` on `FaceLabel(index=...)`)

- [ ] **Step 3: Extend `FaceLabel`**

Replace the `FaceLabel` dataclass in `src/models.py` with:

```python
@dataclass
class FaceLabel:
    name: str
    face_type: str
    area: float
    centroid: tuple[float, float, float]
    normal: Optional[tuple[float, float, float]] = None
    radius: Optional[float] = None
    axis: Optional[tuple[float, float, float]] = None        # cylinder axis direction
    axis_point: Optional[tuple[float, float, float]] = None  # a point on that axis
    index: int = -1                                          # position in features.faces
```

- [ ] **Step 4: Record the axis in the analyzer**

In `src/geometry/analyzer.py` inside `_label_faces`, the `CYLINDER` branch currently reads:

```python
                elif gt == "CYLINDER" and _OCP_AVAILABLE:
                    radius = None
                    try:
                        adaptor = GeomAdaptor_Surface(BRep_Tool.Surface_s(face.wrapped))
                        radius = round(adaptor.Cylinder().Radius(), 3)
                    except Exception:
                        pass
```

Change it to:

```python
                elif gt == "CYLINDER" and _OCP_AVAILABLE:
                    radius = None
                    axis = None
                    axis_point = None
                    try:
                        adaptor = GeomAdaptor_Surface(BRep_Tool.Surface_s(face.wrapped))
                        cyl = adaptor.Cylinder()
                        radius = round(cyl.Radius(), 3)
                        d = cyl.Axis().Direction()
                        loc = cyl.Axis().Location()
                        axis = (round(d.X(), 4), round(d.Y(), 4), round(d.Z(), 4))
                        axis_point = (round(loc.X(), 3), round(loc.Y(), 3), round(loc.Z(), 3))
                    except Exception:
                        pass
```

and pass `axis=axis, axis_point=axis_point` into that branch's `FaceLabel(...)` call. Then replace the last two lines of `_label_faces`:

```python
        labels.sort(key=lambda lbl: -lbl.area)
        labels = labels[:_MAX_LABELED_FACES]
        for i, lbl in enumerate(labels):
            lbl.index = i
        return labels
```

- [ ] **Step 5: Write the summary builder**

```python
# src/agent/summary.py
"""Compact geometry JSON for the prompt: stable face ids, hole groups, pruning, cap."""
from __future__ import annotations

import math

from src.agent.schema import GeometrySummary, HoleGroup, SummaryBody, SummaryFace, Vec3
from src.models import Body, FaceLabel, GeometryFeatures

FACE_CAP = 200
PRUNE_FRACTION = 0.001
PLACEHOLDER_DENSITY_KG_M3 = 7850.0
RADIUS_TOL = 0.02          # 2 percent
AXIS_TOL_DEG = 5.0
PLANE_TOL_MM = 0.5
CENTER_TOL_MM = 0.5
UNITS = {"length": "mm", "force": "N", "mass": "kg"}


def build_summary(features: GeometryFeatures, bodies: list[Body]) -> GeometrySummary:
    labels = list(features.faces)
    if len(labels) > FACE_CAP:
        raise ValueError(f"Part has {len(labels)} labeled faces, above the cap of {FACE_CAP}")

    groups = _group_holes(labels)
    grouped_ids = {fid for g in groups for fid in g.face_ids}

    total_area = features.surface_area or sum(l.area for l in labels)
    keep: list[FaceLabel] = []
    for lbl in labels:
        fid = f"f{lbl.index}"
        if total_area > 0 and lbl.area < PRUNE_FRACTION * total_area and fid not in grouped_ids:
            continue
        keep.append(lbl)

    faces = [SummaryFace(
        id=f"f{lbl.index}",
        body_id=_body_for(lbl, bodies),
        type=_face_type(lbl),
        area_mm2=float(lbl.area),
        centroid_mm=Vec3(x=lbl.centroid[0], y=lbl.centroid[1], z=lbl.centroid[2]),
        normal=Vec3(x=lbl.normal[0], y=lbl.normal[1], z=lbl.normal[2]) if lbl.normal else None,
        radius_mm=lbl.radius,
        label=lbl.name,
    ) for lbl in keep]

    return GeometrySummary(
        units=dict(UNITS),
        bbox_mm=Vec3(x=features.bbox[0], y=features.bbox[1], z=features.bbox[2]),
        volume_mm3=float(features.volume),
        estimated_mass_kg=float(features.volume) * 1e-9 * PLACEHOLDER_DENSITY_KG_M3,
        bodies=[SummaryBody(id=b.id, name=b.name, volume_mm3=b.volume,
                            centroid_mm=Vec3(x=b.centroid[0], y=b.centroid[1], z=b.centroid[2]),
                            bbox_mm=Vec3(x=b.bbox[0], y=b.bbox[1], z=b.bbox[2])) for b in bodies],
        faces=faces,
        hole_groups=groups,
        symmetry_planes=list(features.symmetry_planes),
        thin_walls=bool(features.thin_walls),
    )


def _face_type(lbl: FaceLabel) -> str:
    return lbl.face_type if lbl.face_type in ("planar", "cylindrical") else "other"


def _body_for(lbl: FaceLabel, bodies: list[Body]) -> int:
    """Single-body parts map to that body; otherwise the body whose bbox contains the centroid."""
    if len(bodies) <= 1:
        return bodies[0].id if bodies else 0
    cx, cy, cz = lbl.centroid
    for b in bodies:
        hx, hy, hz = (b.bbox[0] / 2 + 0.5, b.bbox[1] / 2 + 0.5, b.bbox[2] / 2 + 0.5)
        if abs(cx - b.centroid[0]) <= hx and abs(cy - b.centroid[1]) <= hy and abs(cz - b.centroid[2]) <= hz:
            return b.id
    return bodies[0].id


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _parallel(a, b) -> bool:
    c = abs(_dot(a, b)) / (_norm(a) * _norm(b) or 1.0)
    return c >= math.cos(math.radians(AXIS_TOL_DEG))


def _perp_projection(point, axis):
    """Component of point perpendicular to axis (axis is unit length)."""
    t = _dot(point, axis)
    return (point[0] - t * axis[0], point[1] - t * axis[1], point[2] - t * axis[2])


def _group_holes(labels: list[FaceLabel]) -> list[HoleGroup]:
    cyl = [l for l in labels if l.face_type == "cylindrical" and l.radius and l.axis and l.axis_point]
    used: set[int] = set()
    groups: list[HoleGroup] = []
    for i, seed in enumerate(cyl):
        if i in used:
            continue
        members = [seed]
        for j in range(i + 1, len(cyl)):
            if j in used:
                continue
            other = cyl[j]
            same_radius = abs(other.radius - seed.radius) <= RADIUS_TOL * seed.radius
            same_axis = _parallel(other.axis, seed.axis)
            same_plane = abs(_dot(other.centroid, seed.axis) - _dot(seed.centroid, seed.axis)) <= PLANE_TOL_MM
            if same_radius and same_axis and same_plane:
                members.append(other)
                used.add(j)
        centers = _distinct_centers(members, seed.axis)
        if len(centers) < 2:
            continue
        used.add(i)
        groups.append(HoleGroup(
            id=f"hg{len(groups) + 1}",
            face_ids=[f"f{m.index}" for m in members],
            radius_mm=float(seed.radius),
            count=len(centers),
            plane_normal=Vec3(x=seed.axis[0], y=seed.axis[1], z=seed.axis[2]),
            pattern=_pattern(centers),
        ))
    return groups


def _distinct_centers(members: list[FaceLabel], axis) -> list[tuple[float, float, float]]:
    centers: list[tuple[float, float, float]] = []
    for m in members:
        c = _perp_projection(m.axis_point, axis)
        if all(_norm(_sub(c, e)) > CENTER_TOL_MM for e in centers):
            centers.append(c)
    return centers


def _pattern(centers: list[tuple[float, float, float]]) -> str:
    n = len(centers)
    if n == 2:
        return "linear"
    if _collinear(centers):
        return "linear"
    if n == 4 and _is_rectangle(centers):
        return "rectangular"
    cx = tuple(sum(c[k] for c in centers) / n for k in range(3))
    radii = [_norm(_sub(c, cx)) for c in centers]
    if n >= 3 and max(radii) - min(radii) <= 0.02 * max(radii):
        return "circular"
    return "irregular"


def _collinear(centers) -> bool:
    a, b = centers[0], centers[1]
    ab = _sub(b, a)
    L = _norm(ab) or 1.0
    for c in centers[2:]:
        ac = _sub(c, a)
        cross = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        if _norm(cross) / L > CENTER_TOL_MM:
            return False
    return True


def _is_rectangle(centers) -> bool:
    """Four points form a rectangle when both diagonals are equal and share a midpoint."""
    best = None
    for i in range(1, 4):
        others = [k for k in range(1, 4) if k != i]
        d1 = _sub(centers[i], centers[0])
        d2 = _sub(centers[others[1]], centers[others[0]])
        mid1 = tuple((centers[i][k] + centers[0][k]) / 2 for k in range(3))
        mid2 = tuple((centers[others[1]][k] + centers[others[0]][k]) / 2 for k in range(3))
        if _norm(_sub(mid1, mid2)) <= CENTER_TOL_MM and abs(_norm(d1) - _norm(d2)) <= CENTER_TOL_MM:
            best = True
    return bool(best)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_summary.py -q`
Expected: 8 passed

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest -q` → 79 passed (the analyzer and viewer tests still pass because the new `FaceLabel` fields default).

```bash
git add src/models.py src/geometry/analyzer.py src/agent/summary.py tests/test_agent_summary.py
git commit -m "feat(agent): geometry summary builder with hole grouping and pruning"
```

### Task 4: Adapter to SimulationConfig

**Files:**
- Modify: `src/models.py:51-57` (`BoundaryCondition.rationale`), `:86-92` (`BodyMaterial.rationale`), `:95-112` (`SimulationConfig.load_cases/assumptions/questions`), plus new `LoadCaseBlock`
- Create: `src/agent/adapter.py`
- Test: `tests/test_agent_adapter.py`

**Interfaces:**
- Consumes: `SetupProposal`, `GeometrySummary` (Task 1); `GeometryFeatures`, `SimulationConfig`, `BoundaryCondition`, `MeshSettings`, `RefinementZone`, `SolverSettings`, `BodyMaterial`, `ElementType`, `SimulationType` from `src/models.py`; `SmartDefaultsEngine.compute(features, sim_type) -> dict` with key `outputs`; `MaterialDatabase.get_by_id`.
- Produces: `to_config(proposal, summary, features, geometry_path: str, db) -> SimulationConfig`. `G_MM_S2 = 9806.65`. `LoadCaseBlock(name, boundary_conditions, rationale)` dataclass in `src/models.py`. BC type strings: `Fixed Support`, `Frictionless Support`, `Cylindrical Support`, `Displacement`, `Force`, `Pressure`, `Remote Force`, `Bearing Load`, `Acceleration`. Direction strings look like `(0, 0, -1)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_adapter.py
import pytest
from src.agent.adapter import to_config, G_MM_S2
from src.agent.schema import SetupProposal, GeometrySummary
from src.materials.database import MaterialDatabase
from src.models import GeometryFeatures, SimulationType, ElementType, LoadCaseBlock


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"},
        "bbox_mm": vec(100, 50, 20), "volume_mm3": 100000.0, "estimated_mass_kg": 0.785,
        "bodies": [{"id": 0, "name": "bracket", "volume_mm3": 100000.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [
            {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top, 5000 mm²)"},
            {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 1000, "centroid_mm": vec(50, 0, 0), "normal": vec(1, 0, 0), "radius_mm": None, "label": "+X face (right, 1000 mm²)"},
            {"id": "f2", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 0, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
            {"id": "f3", "body_id": 0, "type": "cylindrical", "area_mm2": 250, "centroid_mm": vec(-40, 15, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"},
        ],
        "hole_groups": [{"id": "hg1", "face_ids": ["f2", "f3"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False,
    })


@pytest.fixture
def features():
    return GeometryFeatures(bbox=(100., 50., 20.), volume=100000., surface_area=16500., body_count=1,
                            thin_walls=False, holes=[], symmetry_planes=[], sharp_edges=False)


@pytest.fixture
def proposal():
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": 5, "rationale": "aluminum bracket"}],
        "supports": [{"id": "s1", "target": "hg1", "type": "fixed", "rationale": "bolted"}],
        "loads": [{"id": "l1", "target": "f1", "type": "force", "magnitude": 500.0, "direction": vec(0, 0, -1), "rationale": "mass"},
                  {"id": "l2", "target": "f0", "type": "pressure", "magnitude": 0.2, "direction": vec(0, 0, -1), "rationale": "snow"}],
        "load_cases": [
            {"name": "static 1g", "acceleration_g": vec(0, 0, -1), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "gravity"},
            {"name": "shock 5g", "acceleration_g": vec(0, 0, -5), "load_ids": ["l1", "l2"], "support_ids": ["s1"], "rationale": "pothole"},
        ],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": [{"target": "hg1", "size_mm": 1.0, "reason": "bolt holes"}]},
        "assumptions": ["mass at the free end"], "questions": ["bolt preload?"],
    })


def test_config_basics(proposal, summary, features):
    cfg = to_config(proposal, summary, features, r"C:\parts\bracket.step", MaterialDatabase())
    assert cfg.sim_type == SimulationType.STATIC_STRUCTURAL
    assert cfg.geometry_path.endswith("bracket.step")
    assert cfg.body_materials[0].material_name == "Aluminum Alloy 6061-T6"
    assert cfg.body_materials[0].body_ids == [0]
    assert cfg.body_materials[0].rationale == "aluminum bracket"
    assert cfg.assumptions == ["mass at the free end"] and cfg.questions == ["bolt preload?"]


def test_hole_group_support_expands_to_member_faces(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    fixed = [bc for bc in cfg.boundary_conditions if bc.bc_type == "Fixed Support"]
    assert [bc.target for bc in fixed] == ["Cyl hole #1", "Cyl hole #2"]
    assert fixed[0].rationale == "bolted"


def test_loads_map_units_and_direction(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    force = next(bc for bc in cfg.boundary_conditions if bc.bc_type == "Force")
    assert force.target == "+X face (right, 1000 mm²)" and force.magnitude == 500.0
    assert force.unit == "N" and force.direction == "(0, 0, -1)"
    pressure = next(bc for bc in cfg.boundary_conditions if bc.bc_type == "Pressure")
    assert pressure.unit == "MPa" and pressure.magnitude == 0.2


def test_load_cases_carry_acceleration(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    assert [lc.name for lc in cfg.load_cases] == ["static 1g", "shock 5g"]
    assert all(isinstance(lc, LoadCaseBlock) for lc in cfg.load_cases)
    shock = cfg.load_cases[1]
    accel = next(bc for bc in shock.boundary_conditions if bc.bc_type == "Acceleration")
    assert abs(accel.magnitude - 5 * G_MM_S2) < 1e-6 and accel.unit == "mm/s^2"
    assert accel.direction == "(0, 0, -1)" and accel.target == "All Bodies"
    # shock case: 2 hole faces fixed + l1 + l2 + acceleration
    assert len(shock.boundary_conditions) == 5
    assert len(cfg.load_cases[0].boundary_conditions) == 4


def test_mesh_mapping(proposal, summary, features):
    cfg = to_config(proposal, summary, features, "p.step", MaterialDatabase())
    assert cfg.mesh.global_size_mm == 4.0 and cfg.mesh.element_type == ElementType.SOLID
    assert cfg.mesh.refinement_zones[0].size_mm == 1.0
    assert "bolt holes" in cfg.mesh.refinement_zones[0].description
    assert "total_deformation" in cfg.solver.outputs


def test_existing_config_defaults_unchanged():
    from src.models import SimulationConfig, MeshSettings, SolverSettings
    cfg = SimulationConfig(geometry_path="x", features=None, sim_type=SimulationType.STATIC_STRUCTURAL,
                           body_materials=[], boundary_conditions=[],
                           mesh=MeshSettings(1.0, ElementType.SOLID), solver=SolverSettings())
    assert cfg.load_cases == [] and cfg.assumptions == [] and cfg.questions == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_adapter.py -q`
Expected: FAIL, `ImportError: cannot import name 'LoadCaseBlock'`

- [ ] **Step 3: Extend the models**

In `src/models.py`:

```python
@dataclass
class BoundaryCondition:
    bc_type: str
    target: str
    magnitude: Optional[float] = None
    direction: Optional[str] = None
    unit: str = "N"
    rationale: str = ""
```

```python
@dataclass
class BodyMaterial:
    """Material assignment for one group of bodies sharing the same part name."""
    body_name: str
    body_ids: list[int]
    material_id: int
    material_name: str
    rationale: str = ""
```

Add after `BodyMaterial`:

```python
@dataclass
class LoadCaseBlock:
    """One Static Structural system's worth of boundary conditions, agent path only."""
    name: str
    boundary_conditions: list[BoundaryCondition] = field(default_factory=list)
    rationale: str = ""
```

And extend `SimulationConfig` with three defaulted fields after `solver`:

```python
    load_cases: list[LoadCaseBlock] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Write the adapter**

```python
# src/agent/adapter.py
"""Turn a validated SetupProposal into the existing SimulationConfig dataclasses."""
from __future__ import annotations

from src.agent.schema import GeometrySummary, SetupProposal, Vec3
from src.defaults.engine import SmartDefaultsEngine
from src.materials.database import MaterialDatabase
from src.models import (BodyMaterial, BoundaryCondition, ElementType, GeometryFeatures,
                        LoadCaseBlock, MeshSettings, RefinementZone, SimulationConfig,
                        SimulationType, SolverSettings)

G_MM_S2 = 9806.65

SUPPORT_TYPES = {
    "fixed": "Fixed Support",
    "frictionless": "Frictionless Support",
    "cylindrical": "Cylindrical Support",
    "displacement": "Displacement",
}
LOAD_TYPES = {
    "force": ("Force", "N"),
    "pressure": ("Pressure", "MPa"),
    "remote_force": ("Remote Force", "N"),
    "bearing_load": ("Bearing Load", "N"),
}


def _dir(v: Vec3) -> str:
    return f"({v.x:g}, {v.y:g}, {v.z:g})"


def _labels_for(summary: GeometrySummary, target: str) -> list[str]:
    return [summary.face_by_id(fid).label for fid in summary.target_face_ids(target)]


def _support_bcs(proposal, summary) -> dict[str, list[BoundaryCondition]]:
    out = {}
    for s in proposal.supports:
        out[s.id] = [BoundaryCondition(bc_type=SUPPORT_TYPES[s.type], target=label, rationale=s.rationale)
                     for label in _labels_for(summary, s.target)]
    return out


def _load_bcs(proposal, summary) -> dict[str, list[BoundaryCondition]]:
    out = {}
    for ld in proposal.loads:
        bc_type, unit = LOAD_TYPES[ld.type]
        out[ld.id] = [BoundaryCondition(bc_type=bc_type, target=label, magnitude=ld.magnitude,
                                        direction=_dir(ld.direction), unit=unit, rationale=ld.rationale)
                      for label in _labels_for(summary, ld.target)]
    return out


def _acceleration_bc(lc) -> BoundaryCondition | None:
    g = lc.acceleration_g
    mag = g.length()
    if mag == 0.0:
        return None
    unit_dir = Vec3(x=g.x / mag, y=g.y / mag, z=g.z / mag)
    return BoundaryCondition(bc_type="Acceleration", target="All Bodies", magnitude=mag * G_MM_S2,
                             direction=_dir(unit_dir), unit="mm/s^2", rationale=lc.rationale)


def to_config(proposal: SetupProposal, summary: GeometrySummary, features: GeometryFeatures,
              geometry_path: str, db: MaterialDatabase) -> SimulationConfig:
    body_names = {b.id: b.name for b in summary.bodies}
    body_materials = []
    for m in proposal.materials:
        row = db.get_by_id(m.material_id) or {"name": f"material {m.material_id}"}
        body_materials.append(BodyMaterial(body_name=body_names.get(m.body_id, f"Body {m.body_id + 1}"),
                                           body_ids=[m.body_id], material_id=m.material_id,
                                           material_name=row["name"], rationale=m.rationale))

    supports = _support_bcs(proposal, summary)
    loads = _load_bcs(proposal, summary)
    flat: list[BoundaryCondition] = [bc for bcs in supports.values() for bc in bcs]
    flat += [bc for bcs in loads.values() for bc in bcs]

    load_cases = []
    for lc in proposal.load_cases:
        bcs: list[BoundaryCondition] = []
        for sid in lc.support_ids:
            bcs += supports.get(sid, [])
        for lid in lc.load_ids:
            bcs += loads.get(lid, [])
        accel = _acceleration_bc(lc)
        if accel is not None:
            bcs.append(accel)
        load_cases.append(LoadCaseBlock(name=lc.name, boundary_conditions=bcs, rationale=lc.rationale))

    mesh = MeshSettings(
        global_size_mm=proposal.mesh.global_size_mm,
        element_type=ElementType(proposal.mesh.element_type),
        refinement_zones=[RefinementZone(zone_type="face", size_mm=r.size_mm,
                                         description=f"{', '.join(_labels_for(summary, r.target)) or r.target}: {r.reason}")
                          for r in proposal.mesh.refinement],
    )
    defaults = SmartDefaultsEngine.compute(features, SimulationType.STATIC_STRUCTURAL)
    solver = SolverSettings(substeps=defaults.get("substeps", 1),
                            large_deflection=defaults.get("large_deflection", False),
                            outputs=list(defaults.get("outputs", [])))

    return SimulationConfig(
        geometry_path=geometry_path, features=features, sim_type=SimulationType.STATIC_STRUCTURAL,
        body_materials=body_materials, boundary_conditions=flat, mesh=mesh, solver=solver,
        load_cases=load_cases, assumptions=list(proposal.assumptions), questions=list(proposal.questions),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_adapter.py -q`
Expected: 6 passed

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q` → 85 passed

```bash
git add src/models.py src/agent/adapter.py tests/test_agent_adapter.py
git commit -m "feat(agent): adapter from SetupProposal to SimulationConfig with load cases"
```

### Task 5: Journal Loop Over Load Cases

**Files:**
- Modify: `src/generator/templates/static_structural.wbjn.j2`
- Modify: `src/generator/journal.py:53-74` (`JournalGenerator.write`)
- Test: `tests/test_journal_generator.py` (append)

**Interfaces:**
- Consumes: `SimulationConfig.load_cases: list[LoadCaseBlock]` (Task 4).
- Produces: unchanged signature `JournalGenerator.write(config, output_dir, db=None) -> tuple[str, str]`. With an empty `load_cases` the journal is byte-identical in structure to today (one system). With N load cases the journal creates `system1..systemN`, systems 2..N sharing Engineering Data, Geometry, and Model with `system1`, each with `DisplayText` set to the case name and a comment block listing its boundary conditions.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_journal_generator.py`:

```python
def test_journal_single_system_when_no_load_cases(config, tmp_path):
    wbjn, _ = JournalGenerator.write(config, str(tmp_path))
    text = Path(wbjn).read_text()
    assert text.count("CreateSystem(") == 1
    assert "ComponentsToShare" not in text


def test_journal_one_system_per_load_case(config, tmp_path):
    from dataclasses import replace
    from src.models import LoadCaseBlock
    cases = [
        LoadCaseBlock(name="static 1g", boundary_conditions=[
            BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1"),
            BoundaryCondition(bc_type="Acceleration", target="All Bodies", magnitude=9806.65, direction="(0, 0, -1)", unit="mm/s^2")]),
        LoadCaseBlock(name="shock 5g", boundary_conditions=[
            BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1"),
            BoundaryCondition(bc_type="Force", target="+X face", magnitude=500.0, direction="(0, 0, -1)")]),
    ]
    multi = replace(config, load_cases=cases)
    wbjn, _ = JournalGenerator.write(multi, str(tmp_path))
    text = Path(wbjn).read_text()
    assert text.count("CreateSystem(") == 2
    assert 'system1.DisplayText = "static 1g"' in text
    assert 'system2.DisplayText = "shock 5g"' in text
    assert text.count("ComponentsToShare") == 1
    assert 'GetComponent(Name="Model")' in text
    assert "Force on +X face: 500 N along (0, 0, -1)" in text
    assert text.count('CreateMaterial(Name="Structural Steel")') == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_journal_generator.py -q`
Expected: `test_journal_one_system_per_load_case` FAILS on `assert text.count("CreateSystem(") == 2`

- [ ] **Step 3: Rewrite the static template**

Replace the whole of `src/generator/templates/static_structural.wbjn.j2` with:

```jinja
{% import "_materials.wbjn.j2" as mat %}
# ANSYS Workbench Journal — Static Structural
# Generated by ANSYS Workflow Tool on {{ generated_at }}
# Usage: File → Scripting → Run Script File

SetScriptVersion(Version="22.2 Release")
template1 = GetTemplate(TemplateName="Static Structural")
system1 = template1.CreateSystem()
geometry1 = system1.GetContainer(ComponentName="Geometry")
geometry1.SetFile(FilePath=r"{{ config.geometry_path }}")
{{ mat.engineering_data("system1", materials) }}
{% if load_cases %}
system1.DisplayText = "{{ load_cases[0].name }}"
{% for lc in load_cases[1:] %}
system{{ loop.index + 1 }} = template1.CreateSystem(
    ComponentsToShare=[system1.GetComponent(Name="Engineering Data"),
                       system1.GetComponent(Name="Geometry"),
                       system1.GetComponent(Name="Model")],
    Position="Right",
    RelativeTo=system{{ loop.index }})
system{{ loop.index + 1 }}.DisplayText = "{{ lc.name }}"
{% endfor %}

# --- Load cases: apply these in Mechanical for each system ---
{% for lc in load_cases %}
# system{{ loop.index }} "{{ lc.name }}"{% if lc.rationale %} — {{ lc.rationale }}{% endif %}
{% for bc in lc.boundary_conditions %}
#   {{ bc.bc_type }} on {{ bc.target }}{% if bc.magnitude is not none %}: {{ bc.magnitude|num }} {{ bc.unit }}{% endif %}{% if bc.direction %} along {{ bc.direction }}{% endif %}
{% endfor %}
{% endfor %}
{% endif %}
# Open Mechanical and run mechanical_setup.py via File → Scripting → Run Script File
# to apply mesh, material, solver settings, and output requests.
```

`trim_blocks` strips the newline after each block tag, so the comment lines come out single spaced. The `num` filter renders `500.0` as `500`, which the test string `500 N` expects.

- [ ] **Step 4: Register the number filter and pass load cases**

In `src/generator/journal.py`, after `_ENV` is created add:

```python
def _num(value) -> str:
    return f"{value:g}"


_ENV.filters["num"] = _num
```

Then in `JournalGenerator.write`, change the render call to:

```python
        content = _ENV.get_template(template_name).render(
            config=config,
            materials=materials,
            load_cases=getattr(config, "load_cases", []),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_journal_generator.py -q`
Expected: 18 passed

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q` → 87 passed

```bash
git add src/generator/journal.py src/generator/templates/static_structural.wbjn.j2 tests/test_journal_generator.py
git commit -m "feat(generator): one Static Structural system per load case"
```

---

### Task 6: Report Sections for Load Cases, Rationale, Assumptions

**Files:**
- Modify: `src/generator/templates/settings_summary.html.j2`
- Test: `tests/test_journal_generator.py` (append)

**Interfaces:**
- Consumes: `SimulationConfig.load_cases`, `.assumptions`, `.questions`, `BoundaryCondition.rationale`, `BodyMaterial.rationale` (Task 4).
- Produces: `SummaryGenerator.write` unchanged; HTML gains a "Load Cases" table, a "Rationale" column on Materials and Boundary Conditions, and "Assumptions" and "Open Questions" lists, all omitted when empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_journal_generator.py`:

```python
def test_summary_omits_agent_sections_when_empty(config, tmp_path):
    html = Path(SummaryGenerator.write(config, str(tmp_path))).read_text()
    assert "Load Cases" not in html and "Assumptions" not in html and "Open Questions" not in html


def test_summary_renders_load_cases_and_rationale(config, tmp_path):
    from dataclasses import replace
    from src.models import LoadCaseBlock, BodyMaterial
    agent_cfg = replace(
        config,
        body_materials=[BodyMaterial(body_name="bracket", body_ids=[0], material_id=1,
                                     material_name="Structural Steel", rationale="brief says mild steel")],
        boundary_conditions=[BoundaryCondition(bc_type="Fixed Support", target="Cyl hole #1", rationale="bolted to frame")],
        load_cases=[LoadCaseBlock(name="shock 5g", rationale="pothole per ISO 16750-3", boundary_conditions=[
            BoundaryCondition(bc_type="Acceleration", target="All Bodies", magnitude=49033.25, direction="(0, 0, -1)", unit="mm/s^2")])],
        assumptions=["mass hangs from the free end"],
        questions=["bolt preload?"],
    )
    html = Path(SummaryGenerator.write(agent_cfg, str(tmp_path))).read_text()
    assert "Load Cases" in html and "shock 5g" in html and "pothole per ISO 16750-3" in html
    assert "brief says mild steel" in html and "bolted to frame" in html
    assert "Assumptions" in html and "mass hangs from the free end" in html
    assert "Open Questions" in html and "bolt preload?" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_journal_generator.py -q`
Expected: `test_summary_renders_load_cases_and_rationale` FAILS on `"Load Cases" in html`

- [ ] **Step 3: Edit the HTML template**

In `src/generator/templates/settings_summary.html.j2` replace the Materials table with:

```html
<h2>Materials</h2>
<table>
<tr><th>Body</th><th>Instances</th><th>Material</th><th>Rationale</th></tr>
{% for bm in config.body_materials %}
<tr><td>{{ bm.body_name }}</td><td>{{ bm.body_ids|length }}</td><td>{{ bm.material_name }}</td><td class="note">{{ bm.rationale or "—" }}</td></tr>
{% else %}
<tr><td colspan="4"><em>No materials assigned</em></td></tr>
{% endfor %}
</table>
```

Replace the Boundary Conditions table with:

```html
<h2>Boundary Conditions</h2>
<table>
<tr><th>Type</th><th>Target</th><th>Magnitude</th><th>Direction</th><th>Rationale</th></tr>
{% for bc in config.boundary_conditions %}
<tr><td>{{ bc.bc_type }}</td><td>{{ bc.target }}</td>
<td>{% if bc.magnitude is not none %}{{ bc.magnitude }} {{ bc.unit }}{% else %}—{% endif %}</td>
<td>{{ bc.direction or "—" }}</td><td class="note">{{ bc.rationale or "—" }}</td></tr>
{% else %}
<tr><td colspan="5"><em>None defined</em></td></tr>
{% endfor %}
</table>

{% if config.load_cases %}
<h2>Load Cases</h2>
<table>
<tr><th>Case</th><th>Boundary conditions</th><th>Rationale</th></tr>
{% for lc in config.load_cases %}
<tr><td>{{ lc.name }}</td>
<td>{% for bc in lc.boundary_conditions %}{{ bc.bc_type }} on {{ bc.target }}{% if bc.magnitude is not none %} ({{ bc.magnitude|round(2) }} {{ bc.unit }}{% if bc.direction %} along {{ bc.direction }}{% endif %}){% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td>
<td class="note">{{ lc.rationale or "—" }}</td></tr>
{% endfor %}
</table>
{% endif %}
```

And before the closing `<p class="note" style="margin-top:32px">` add:

```html
{% if config.assumptions %}
<h2>Assumptions</h2>
<ul>
{% for a in config.assumptions %}<li>{{ a }}</li>
{% endfor %}</ul>
{% endif %}
{% if config.questions %}
<h2>Open Questions</h2>
<ul>
{% for q in config.questions %}<li>{{ q }}</li>
{% endfor %}</ul>
{% endif %}
```

The `td:first-child{width:35%}` rule stays; it only affects the first column.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_journal_generator.py -q`
Expected: 20 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q` → 89 passed

```bash
git add src/generator/templates/settings_summary.html.j2 tests/test_journal_generator.py
git commit -m "feat(generator): report shows load cases, rationale, assumptions, questions"
```

### Task 7: Playbook and Proposal Agent

**Files:**
- Create: `src/agent/playbook.md`
- Create: `src/agent/proposer.py`
- Test: `tests/test_agent_proposer.py`
- Modify: `requirements.txt` (add `anthropic>=0.69`)
- Modify: `.gitignore` (add `logs/`)

**Interfaces:**
- Consumes: `SetupProposal`, `GeometrySummary` (Task 1).
- Produces:
  - `load_playbook() -> str` and `playbook_hash() -> str` (first 12 hex of sha256 of the file).
  - `build_system_prompt(playbook: str) -> list[dict]` returning `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]`.
  - `build_user_message(summary, brief, prior=None, feedback=None, instruction=None) -> str`.
  - `propose(summary, brief, playbook=None, prior=None, feedback=None, instruction=None, client=None, model="claude-opus-5", session_id="", log_path=DEFAULT_LOG) -> ProposalResult` where `ProposalResult(proposal: SetupProposal, input_tokens: int, output_tokens: int, cache_read_tokens: int, latency_s: float)`.
  - `DEFAULT_LOG = Path("logs/proposals.jsonl")`. `MODEL = "claude-opus-5"`. `MAX_TOKENS = 16000`.

- [ ] **Step 1: Install the SDK and record it**

Run: `pip install -U anthropic` then append `anthropic>=0.69` to `requirements.txt` and `logs/` to `.gitignore` (create `.gitignore` if absent).

- [ ] **Step 2: Write the playbook**

Create `src/agent/playbook.md`:

```markdown
# FEA Setup Playbook

You propose Static Structural setups for a single part or small assembly. Units are mm, N, kg, MPa, and g. Axes are the summary's axes. Every support, load, load case, and refinement carries a one-line rationale an engineer could challenge.

## Geometry classes and standard load-case sets

**Brackets and mounts.** Bolted at a hole group, carrying a hung or mounted mass. Supports: fixed on the bolt-hole group, or cylindrical on the hole faces plus a frictionless support on the mating planar face when the brief mentions a clamped flange. Loads: force at the mounting face or hole group of the carried component. Cases: static 1 g down; dynamic 3 g in each of the three axes as separate cases when the part is vehicle mounted (ISO 16750-3 for road vehicles); shock 20 g down for battery hardware (ECE R100, SAE J2380). Do not put a load on the same target as a support.

**Trays and enclosures.** Thin sheet with flanges, supported on standoffs or a rim. Supports: fixed on the standoff holes or frictionless on the rim underside plus a displacement of zero on one edge to remove rigid-body motion. Loads: pressure from contents on the floor, or force at internal mount points. Cases: 1 g plus contents; 3 g vertical for vehicle use. Prefer Shell elements when thin_walls is true.

**Frame sections and weldments.** Tubes or channels with end connections. Supports: fixed on one end face, frictionless on a mid-span pad if the brief says it rests on something. Loads: force or remote force at the far end or at a bracket location. Cases: rated load, then 1.5 times rated load as an overload case. Keep global mesh coarse and refine at welds and corners.

**Shafts and pins.** Cylindrical, supported in bearings or bores. Supports: cylindrical on bearing journal faces (tangential free, radial fixed). Loads: bearing load on the loaded journal, torque as a remote force pair when the brief gives torque. Cases: rated radial load; combined radial plus axial if the brief mentions thrust.

**Lids and panels.** Flat, fastened around the edge. Supports: fixed on the fastener hole group. Loads: uniform pressure on the outer face (snow, wind, handling), point force at the center for a hand push case. Cases: pressure, then 1 kN hand load at center.

## Support selection

Pick the faces that constrain the part the way the real assembly does. A fixed support on a large planar face is almost always too stiff; prefer the hole group or a small contact patch. Never fix every face of a body. Never fix more than half a body's surface. Use cylindrical supports on hole faces when the bolt allows rotation, fixed when it is torqued against a flange. Use a frictionless support on a face that bears against something but is not attached. Use symmetry only when the brief and geometry both support it and say so in assumptions.

## Load application

Force for a resultant applied through a face. Pressure for distributed loads on an area (MPa). Remote force when the load acts at a point away from the part, such as a mass on a lever arm. Bearing load for a shaft in a bore. Directions are unit vectors in the summary axes; gravity is usually -Z unless the summary's labels show otherwise. Inertial cases go in `acceleration_g`, not as forces; the solver applies them to every body.

## Magnitudes

If the brief gives a mass, convert to force with 9.81 m/s² and state it. If the brief gives no numbers, pick a representative value from the geometry class above and list it under assumptions. Keep accelerations at or below 30 g. Keep pressures well below the material yield.

## Mesh sizing

Global element size: about 1/20 of the smallest bounding-box dimension, clamped to 1 to 10 percent of the largest dimension. Refine hole groups to hole radius divided by 4, fillets and sharp corners to global divided by 4. Shell elements only when thin_walls is true.

## Material selection

Map brief keywords to the database: steel, mild steel, structural → Structural Steel (id 1). stainless → Stainless Steel 316L (2). aluminum, aluminium, 6061 → Aluminum Alloy 6061-T6 (5). 7075 → Aluminum Alloy 7075-T6 (6). 5052 → Aluminum 5052-H32 (8). titanium → Titanium Ti-6Al-4V (9). nylon → Nylon 6 PA6 (17). polycarbonate → Polycarbonate PC (16). ABS → ABS (18). If unstated, use Structural Steel for brackets and frames, Aluminum 6061-T6 for trays and lids, and say so in assumptions.

## Assumptions and questions

List every assumption you made where the brief was silent. Ask one to three questions you would put to the engineer, in order of how much the answer would change the setup.
```

- [ ] **Step 3: Write the failing tests**

```python
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
    for key in ("timestamp", "session_id", "model", "input_tokens", "output_tokens", "cache_read_tokens",
                "latency_s", "playbook_hash", "brief", "summary_hash", "proposal"):
        assert key in row
    assert row["session_id"] == "abc" and row["proposal"]["materials"][0]["material_id"] == 1


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="live smoke test needs ANTHROPIC_API_KEY")
def test_live_smoke(summary, tmp_path):
    result = propose(summary, "A mild steel bracket bolted through its top face, carrying a 2 kg sensor.",
                     log_path=tmp_path / "log.jsonl")
    assert result.proposal.supports and result.proposal.load_cases
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_proposer.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent.proposer'`

- [ ] **Step 5: Write the proposer**

```python
# src/agent/proposer.py
"""One structured-output call to Claude that returns a SetupProposal, plus JSONL logging."""
from __future__ import annotations

import hashlib
import json
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
        "validator": None,
    }
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
```

The `validator` field is filled by the pipeline in Task 8 through `append_validator_outcome`; it is `None` here so the row shape is stable.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_proposer.py -q`
Expected: 6 passed, 1 skipped

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest -q` → 95 passed, 1 skipped

```bash
git add src/agent/playbook.md src/agent/proposer.py tests/test_agent_proposer.py requirements.txt .gitignore
git commit -m "feat(agent): proposal agent with playbook, structured output, and JSONL log"
```

---

### Task 8: Pipeline with One Validator Retry

**Files:**
- Create: `src/agent/pipeline.py`
- Test: `tests/test_agent_pipeline.py`

**Interfaces:**
- Consumes: `propose` and `ProposalResult` (Task 7), `validate` (Task 2), `SetupProposal`, `GeometrySummary`.
- Produces: `run_pipeline(summary, brief, db, prior=None, instruction=None, session_id="", propose_fn=propose, log_path=DEFAULT_LOG) -> PipelineResult` with `PipelineResult(proposal: SetupProposal, messages: list[str], attempts: int, valid: bool, tokens: dict)`. Also `append_validator_outcome(log_path, session_id, messages)` which rewrites the last log row's `validator` field.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_pipeline.py
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


def test_validator_outcome_written_to_log(summary, tmp_path):
    from src.agent.proposer import propose as real_propose  # noqa: F401  (ensures import path exists)
    from src.agent.pipeline import append_validator_outcome
    log = tmp_path / "l.jsonl"
    log.write_text(json.dumps({"session_id": "s", "validator": None}) + "\n")
    append_validator_outcome(log, "s", ["rule2: x"])
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["validator"] == {"valid": False, "messages": ["rule2: x"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_pipeline.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent.pipeline'`

- [ ] **Step 3: Write the pipeline**

```python
# src/agent/pipeline.py
"""propose → validate → at most one revision call. No third attempt."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.agent.proposer import DEFAULT_LOG, ProposalResult, propose
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
    """Fill the `validator` field of the most recent log row for this session."""
    log_path = Path(log_path)
    if not log_path.exists():
        return
    lines = log_path.read_text(encoding="utf-8").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        try:
            row = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if row.get("session_id") == session_id and row.get("validator") is None:
            row["validator"] = {"valid": not messages, "messages": list(messages)}
            lines[i] = json.dumps(row)
            break
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_pipeline.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q` → 100 passed, 1 skipped

```bash
git add src/agent/pipeline.py tests/test_agent_pipeline.py
git commit -m "feat(agent): pipeline with validation and a single revision retry"
```

### Task 9: Off-Screen Renderer

**Files:**
- Create: `src/agent/render.py`
- Test: `tests/test_agent_render.py`

**Interfaces:**
- Consumes: `NamedSolid` from `src/geometry/analyzer.py` (`.body: Body`, `.shape: cq.Shape`); `GeometrySummary` (Task 1). Tessellation tolerances copied from `src/wizard/viewer.py:30-31`.
- Produces: `render_image(named_solids, summary, support_targets: list[str], load_targets: list[str]) -> numpy.ndarray` (H by W by 3, uint8, 900 by 1200) and `render_png(...) -> bytes` with the same arguments. Colors `SUPPORT_RGB = (63, 111, 158)`, `LOAD_RGB = (217, 138, 43)`, `BASE_RGB = (208, 212, 216)`. Faces are matched to summary ids by centroid and area, never by index.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_render.py
import cadquery as cq
import numpy as np
import pytest
from src.agent.render import render_image, render_png, SUPPORT_RGB, LOAD_RGB
from src.agent.summary import build_summary
from src.geometry.analyzer import GeometryAnalyzer


@pytest.fixture(scope="session")
def box_hole(tmp_path_factory):
    path = tmp_path_factory.mktemp("cad") / "box_hole.step"
    shape = cq.Workplane("XY").box(100, 50, 20).faces(">Z").workplane().hole(10)
    cq.exporters.export(shape, str(path))
    features, solids = GeometryAnalyzer.analyze_with_solids(str(path))
    return features, solids, build_summary(features, [ns.body for ns in solids])


def _count_color(img, rgb, tol=25):
    diff = np.abs(img[:, :, :3].astype(int) - np.array(rgb)[None, None, :])
    return int((diff.max(axis=2) <= tol).sum())


def test_render_image_shape(box_hole):
    features, solids, summary = box_hole
    img = render_image(solids, summary, [], [])
    assert img.shape[0] == 900 and img.shape[1] == 1200 and img.dtype == np.uint8


def test_render_colors_support_and_load_faces(box_hole):
    features, solids, summary = box_hole
    top = next(f.id for f in summary.faces if f.label.startswith("+Z"))
    right = next(f.id for f in summary.faces if f.label.startswith("+X"))
    plain = render_image(solids, summary, [], [])
    colored = render_image(solids, summary, [top], [right])
    assert _count_color(colored, SUPPORT_RGB) > 500 > _count_color(plain, SUPPORT_RGB)
    assert _count_color(colored, LOAD_RGB) > 200 > _count_color(plain, LOAD_RGB)


def test_render_png_bytes(box_hole):
    features, solids, summary = box_hole
    data = render_png(solids, summary, [], [])
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_agent_render.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.agent.render'`

- [ ] **Step 3: Write the renderer**

```python
# src/agent/render.py
"""Off-screen pyvista render with support faces blue and load faces orange. No Qt."""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pyvista as pv

from src.agent.schema import GeometrySummary

SUPPORT_RGB = (63, 111, 158)
LOAD_RGB = (217, 138, 43)
BASE_RGB = (208, 212, 216)
WINDOW = (1200, 900)
_TESS_TOL_LINEAR = 0.1
_TESS_TOL_ANGULAR = 0.2
_MATCH_TOL_MM = 0.5
_AREA_TOL = 0.02


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % rgb


def _face_meshes(named_solid):
    """Yield (centroid, area, PolyData) per face of one solid."""
    for face in named_solid.shape.Faces():
        try:
            pd = face.toVtkPolyData(_TESS_TOL_LINEAR, _TESS_TOL_ANGULAR)
        except Exception:
            try:
                pd = face.toVtkPolyData()
            except Exception:
                continue
        if pd is None or pd.GetNumberOfCells() == 0:
            continue
        c = face.Center()
        yield (c.x, c.y, c.z), face.Area(), pv.wrap(pd)


def _match(summary: GeometrySummary, centroid, area) -> str | None:
    for f in summary.faces:
        c = f.centroid_mm
        if (abs(c.x - centroid[0]) <= _MATCH_TOL_MM and abs(c.y - centroid[1]) <= _MATCH_TOL_MM
                and abs(c.z - centroid[2]) <= _MATCH_TOL_MM
                and abs(f.area_mm2 - area) <= _AREA_TOL * max(f.area_mm2, 1.0)):
            return f.id
    return None


def _expand(summary: GeometrySummary, targets: list[str]) -> set[str]:
    out: set[str] = set()
    for t in targets:
        out.update(summary.target_face_ids(t))
    return out


def render_image(named_solids, summary: GeometrySummary, support_targets: list[str],
                 load_targets: list[str]) -> np.ndarray:
    support_faces = _expand(summary, support_targets)
    load_faces = _expand(summary, load_targets)
    plotter = pv.Plotter(off_screen=True, window_size=list(WINDOW))
    plotter.set_background("white")
    for ns in named_solids:
        for centroid, area, mesh in _face_meshes(ns):
            fid = _match(summary, centroid, area)
            color = BASE_RGB
            if fid in support_faces:
                color = SUPPORT_RGB
            elif fid in load_faces:
                color = LOAD_RGB
            plotter.add_mesh(mesh, color=_hex(color), smooth_shading=False, show_edges=False)
    plotter.view_isometric()
    plotter.camera.zoom(1.2)
    img = plotter.screenshot(return_img=True)
    plotter.close()
    return np.asarray(img)[:, :, :3].astype(np.uint8)


def render_png(named_solids, summary: GeometrySummary, support_targets: list[str],
               load_targets: list[str]) -> bytes:
    support_faces = _expand(summary, support_targets)
    load_faces = _expand(summary, load_targets)
    plotter = pv.Plotter(off_screen=True, window_size=list(WINDOW))
    plotter.set_background("white")
    for ns in named_solids:
        for centroid, area, mesh in _face_meshes(ns):
            fid = _match(summary, centroid, area)
            color = BASE_RGB
            if fid in support_faces:
                color = SUPPORT_RGB
            elif fid in load_faces:
                color = LOAD_RGB
            plotter.add_mesh(mesh, color=_hex(color), smooth_shading=False, show_edges=False)
    plotter.view_isometric()
    plotter.camera.zoom(1.2)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        plotter.screenshot(path)
        plotter.close()
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
```

If `render_image` raises about a missing display on Linux, call `pv.start_xvfb()` once at import when `os.name != "nt"` and `DISPLAY` is unset; the Dockerfile in Task 13 installs `xvfb` for this.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_render.py -q`
Expected: 3 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q` → 103 passed, 1 skipped

```bash
git add src/agent/render.py tests/test_agent_render.py
git commit -m "feat(agent): off-screen render with colored support and load faces"
```

---

### Task 10: Web App and Single-Page UI

**Files:**
- Create: `src/web/__init__.py` (empty)
- Create: `src/web/app.py`
- Create: `src/web/static/index.html`
- Test: `tests/test_web_app.py`
- Modify: `requirements.txt` (add `fastapi>=0.115`, `uvicorn>=0.30`, `python-multipart>=0.0.9`, `httpx>=0.27`)

**Interfaces:**
- Consumes: `GeometryAnalyzer.analyze_with_solids`, `build_summary`, `run_pipeline`, `to_config`, `render_png`, `JournalGenerator.write`, `SummaryGenerator.write`, `MaterialDatabase`.
- Produces: FastAPI `app` in `src/web/app.py`; `SESSIONS: dict[str, Session]`; `Session` dataclass with `id, created, last_used, geometry_path, features, solids, summary, proposal, messages, valid, calls, history`; settings `CALLS_PER_SESSION` (env, default 10), `SESSION_CAP_PER_HOUR` (env, default 50), `SESSION_TTL_S = 3600`, `MAX_UPLOAD_BYTES = 20 * 1024 * 1024`. Endpoints exactly as the spec table. `app.state.propose_fn` is the injection point for tests.

- [ ] **Step 1: Install and record dependencies**

Run: `pip install "fastapi>=0.115" "uvicorn>=0.30" "python-multipart>=0.0.9" "httpx>=0.27"` and append those four lines to `requirements.txt`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_web_app.py
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


def test_calls_per_session_cap(client, step_bytes, monkeypatch):
    monkeypatch.setattr(webapp, "CALLS_PER_SESSION", 2)
    sid = upload(client, step_bytes).json()["session_id"]
    assert client.post(f"/session/{sid}/propose", json={"brief": "A"}).status_code == 200
    assert client.post(f"/session/{sid}/revise", json={"instruction": "b"}).status_code == 200
    r = client.post(f"/session/{sid}/revise", json={"instruction": "c"})
    assert r.status_code == 429 and "2" in r.json()["detail"]


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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_web_app.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.web'`

- [ ] **Step 4: Write the app**

```python
# src/web/app.py
"""FastAPI front end: upload → propose → revise → download. In-memory sessions."""
from __future__ import annotations

import base64
import io
import os
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from src.agent.adapter import to_config
from src.agent.pipeline import run_pipeline
from src.agent.proposer import DEFAULT_LOG, propose
from src.agent.render import render_png
from src.agent.schema import GeometrySummary, SetupProposal
from src.agent.summary import build_summary
from src.generator.journal import JournalGenerator
from src.generator.summary import SummaryGenerator
from src.geometry.analyzer import GeometryAnalyzer
from src.materials.database import MaterialDatabase

CALLS_PER_SESSION = int(os.environ.get("CALLS_PER_SESSION", "10"))
SESSION_CAP_PER_HOUR = int(os.environ.get("SESSION_CAP_PER_HOUR", "50"))
SESSION_TTL_S = 3600
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
LOG_PATH = DEFAULT_LOG
STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class Session:
    id: str
    created: float
    last_used: float
    geometry_path: str
    features: object
    solids: list
    summary: GeometrySummary
    proposal: Optional[SetupProposal] = None
    messages: list[str] = field(default_factory=list)
    valid: bool = False
    calls: int = 0
    history: list[dict] = field(default_factory=list)
    brief: str = ""


SESSIONS: dict[str, Session] = {}
SESSION_STARTS: list[float] = []
DB = MaterialDatabase()

app = FastAPI(title="FEA Setup Agent")
app.state.propose_fn = propose


class BriefIn(BaseModel):
    brief: str


class InstructionIn(BaseModel):
    instruction: str


def _sweep() -> None:
    now = time.time()
    for sid in [s for s, sess in SESSIONS.items() if now - sess.last_used > SESSION_TTL_S]:
        _drop(sid)
    SESSION_STARTS[:] = [t for t in SESSION_STARTS if now - t < 3600]


def _drop(sid: str) -> None:
    sess = SESSIONS.pop(sid, None)
    if sess:
        try:
            os.remove(sess.geometry_path)
        except OSError:
            pass


def _get(sid: str) -> Session:
    _sweep()
    sess = SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "Session not found or expired. Upload the part again.")
    sess.last_used = time.time()
    return sess


def _b64_render(sess: Session) -> str:
    supports = [s.target for s in sess.proposal.supports] if sess.proposal else []
    loads = [l.target for l in sess.proposal.loads] if sess.proposal else []
    return base64.b64encode(render_png(sess.solids, sess.summary, supports, loads)).decode("ascii")


def _proposal_payload(sess: Session, attempts: int, tokens: dict) -> dict:
    return {
        "proposal": sess.proposal.model_dump(),
        "messages": sess.messages,
        "valid": sess.valid,
        "attempts": attempts,
        "tokens": tokens,
        "render_png_base64": _b64_render(sess),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/session")
async def create_session(file: UploadFile = File(...)):
    _sweep()
    if len(SESSION_STARTS) >= SESSION_CAP_PER_HOUR:
        raise HTTPException(429, f"Session cap of {SESSION_CAP_PER_HOUR} per hour reached. Try again later.")
    name = (file.filename or "").lower()
    if not name.endswith((".step", ".stp")):
        raise HTTPException(400, "Only STEP files (.step, .stp) are accepted on this path.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is {len(data) / 1e6:.1f} MB; the limit is 20 MB.")
    fd, path = tempfile.mkstemp(suffix=".step")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        features, solids = GeometryAnalyzer.analyze_with_solids(path)
        summary = build_summary(features, [ns.body for ns in solids])
    except ValueError as e:
        os.remove(path)
        raise HTTPException(400, str(e))
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, f"Could not read this STEP file: {e}")
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    SESSIONS[sid] = Session(id=sid, created=now, last_used=now, geometry_path=path,
                            features=features, solids=solids, summary=summary)
    SESSION_STARTS.append(now)
    return {"session_id": sid, "summary": summary.model_dump(), "render_png_base64": _b64_render(SESSIONS[sid])}


def _run(sess: Session, brief: str, instruction: Optional[str]) -> dict:
    if sess.calls >= CALLS_PER_SESSION:
        raise HTTPException(429, f"This session used its {CALLS_PER_SESSION} model calls. Upload again to start over.")
    sess.calls += 1
    try:
        result = run_pipeline(sess.summary, brief, DB, prior=sess.proposal if instruction else None,
                              instruction=instruction, session_id=sess.id,
                              propose_fn=app.state.propose_fn, log_path=LOG_PATH)
    except Exception as e:  # API errors surface as a plain message; the UI shows a retry button
        raise HTTPException(502, f"Model call failed: {e}")
    sess.proposal, sess.messages, sess.valid = result.proposal, result.messages, result.valid
    sess.history.append({"role": "user", "text": instruction or brief})
    sess.history.append({"role": "agent", "valid": result.valid, "messages": result.messages})
    sess.brief = brief
    return _proposal_payload(sess, result.attempts, result.tokens)


@app.post("/session/{sid}/propose")
def propose_endpoint(sid: str, body: BriefIn):
    sess = _get(sid)
    sess.proposal = None
    return _run(sess, body.brief, None)


@app.post("/session/{sid}/revise")
def revise_endpoint(sid: str, body: InstructionIn):
    sess = _get(sid)
    if sess.proposal is None:
        raise HTTPException(409, "Nothing to revise yet. Submit a brief first.")
    return _run(sess, sess.brief, body.instruction)


@app.get("/session/{sid}/download")
def download(sid: str):
    sess = _get(sid)
    if sess.proposal is None or not sess.valid:
        raise HTTPException(409, "Download needs a valid proposal. Fix the validator messages first.")
    config = to_config(sess.proposal, sess.summary, sess.features, sess.geometry_path, DB)
    with tempfile.TemporaryDirectory() as out:
        wbjn, _ = JournalGenerator.write(config, out, DB)
        html = SummaryGenerator.write(config, out)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(wbjn, "simulation_setup.wbjn")
            z.write(html, "settings_summary.html")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="fea_setup_{sid}.zip"'})
```

- [ ] **Step 5: Write the page**

Create `src/web/static/index.html`. No framework, no build step. Left column: upload, brief, chat history, revise box. Right column: render, five tables, assumptions, questions, download button.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FEA Setup Agent</title>
<style>
  body{margin:0;font:15px/1.45 system-ui,Segoe UI,Arial,sans-serif;color:#1c2430;background:#edeff1}
  header{padding:14px 24px;background:#1c2430;color:#fff;font-weight:600;letter-spacing:.02em}
  main{display:grid;grid-template-columns:380px 1fr;gap:20px;padding:20px;max-width:1400px;margin:0 auto}
  section{background:#fff;border:1px solid #c9cfd6;padding:14px}
  h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#6c7683;margin:0 0 8px}
  textarea{width:100%;box-sizing:border-box;min-height:110px;font:inherit;padding:8px;border:1px solid #c9cfd6}
  button{font:inherit;padding:8px 14px;border:0;background:#3f6f9e;color:#fff;cursor:pointer;margin-top:8px}
  button:disabled{background:#9aa5b2;cursor:default}
  table{border-collapse:collapse;width:100%;font-size:14px;margin-bottom:14px}
  th{text-align:left;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#6c7683;border-bottom:1px solid #1c2430;padding:4px 8px 6px 0}
  td{padding:6px 8px 6px 0;border-top:1px solid #e3e6ea;vertical-align:top}
  td.r{color:#6c7683}
  #render{width:100%;border:1px solid #c9cfd6;background:#fff}
  .msg{padding:8px 10px;margin:6px 0;border-left:3px solid #c9cfd6;background:#f6f7f8;font-size:14px}
  .msg.user{border-color:#3f6f9e}
  .msg.bad{border-color:#d98a2b}
  .err{color:#a33;margin-top:8px}
  .legend span{display:inline-block;width:12px;height:12px;margin:0 4px 0 12px;vertical-align:middle}
  ul{margin:4px 0 12px 18px}
  #status{font-size:13px;color:#6c7683;margin-top:6px}
</style>
</head>
<body>
<header>FEA Setup Agent — Static Structural</header>
<main>
  <div>
    <section>
      <h2>1 · Part</h2>
      <input type="file" id="file" accept=".step,.stp">
      <div id="status"></div>
    </section>
    <section style="margin-top:20px">
      <h2>2 · Brief</h2>
      <textarea id="brief" placeholder="What does this part do? Material if known, how it is mounted, what loads it sees. Example: Mild steel bracket bolted to a trailer frame through the four holes, carrying a 12 kg battery box on its top face. Road use."></textarea>
      <button id="go" disabled>Propose setup</button>
      <div class="err" id="err"></div>
    </section>
    <section style="margin-top:20px">
      <h2>3 · Revise</h2>
      <div id="chat"></div>
      <textarea id="instruction" placeholder="Change something: use aluminum, add a 3 g lateral case, move the load to the front face…" style="min-height:70px"></textarea>
      <button id="revise" disabled>Revise</button>
    </section>
  </div>
  <div>
    <section>
      <h2>Render <span class="legend"><span style="background:#3f6f9e"></span>support <span style="background:#d98a2b"></span>load</span></h2>
      <img id="render" alt="part render">
    </section>
    <section style="margin-top:20px" id="proposal" hidden>
      <h2>Proposal</h2>
      <div id="messages"></div>
      <table id="t-materials"></table>
      <table id="t-supports"></table>
      <table id="t-loads"></table>
      <table id="t-cases"></table>
      <table id="t-mesh"></table>
      <h2>Assumptions</h2><ul id="assumptions"></ul>
      <h2>Questions for the engineer</h2><ul id="questions"></ul>
      <button id="download" disabled>Download journal + report</button>
    </section>
  </div>
</main>
<script>
let sid = null, summary = null;
const $ = id => document.getElementById(id);
const face = t => { const f = (summary.faces || []).find(x => x.id === t); if (f) return f.label; const g = (summary.hole_groups || []).find(x => x.id === t); return g ? `${g.count} holes Ø${(2*g.radius_mm).toFixed(1)} (${g.pattern})` : t; };
const vec = v => `(${v.x}, ${v.y}, ${v.z})`;
function table(id, head, rows) { $(id).innerHTML = `<tr>${head.map(h => `<th>${h}</th>`).join('')}</tr>` + rows.map(r => `<tr>${r.map((c, i) => `<td class="${i === r.length - 1 ? 'r' : ''}">${c}</td>`).join('')}</tr>`).join(''); }
function show(body) {
  $('render').src = 'data:image/png;base64,' + body.render_png_base64;
  $('proposal').hidden = false;
  const p = body.proposal;
  $('messages').innerHTML = body.valid ? '' : body.messages.map(m => `<div class="msg bad">${m}</div>`).join('');
  table('t-materials', ['Body', 'Material id', 'Rationale'], p.materials.map(m => [m.body_id, m.material_id, m.rationale]));
  table('t-supports', ['Support', 'Target', 'Type', 'Rationale'], p.supports.map(s => [s.id, face(s.target), s.type, s.rationale]));
  table('t-loads', ['Load', 'Target', 'Type', 'Magnitude', 'Direction', 'Rationale'], p.loads.map(l => [l.id, face(l.target), l.type, l.magnitude, vec(l.direction), l.rationale]));
  table('t-cases', ['Case', 'Accel (g)', 'Loads', 'Supports', 'Rationale'], p.load_cases.map(c => [c.name, vec(c.acceleration_g), c.load_ids.join(', '), c.support_ids.join(', '), c.rationale]));
  table('t-mesh', ['Mesh', 'Value', 'Reason'], [['Global size', p.mesh.global_size_mm + ' mm', ''], ['Elements', p.mesh.element_type, '']].concat(p.mesh.refinement.map(r => ['Refine ' + face(r.target), r.size_mm + ' mm', r.reason])));
  $('assumptions').innerHTML = p.assumptions.map(a => `<li>${a}</li>`).join('') || '<li>none</li>';
  $('questions').innerHTML = p.questions.map(q => `<li>${q}</li>`).join('') || '<li>none</li>';
  $('download').disabled = !body.valid;
  $('revise').disabled = false;
}
function chat(text, cls) { const d = document.createElement('div'); d.className = 'msg ' + cls; d.textContent = text; $('chat').appendChild(d); }
async function call(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({ detail: r.statusText }));
  if (!r.ok) throw new Error(body.detail || 'request failed');
  return body;
}
$('file').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  $('status').textContent = 'Reading part…'; $('err').textContent = '';
  const fd = new FormData(); fd.append('file', f);
  try {
    const body = await call('/session', { method: 'POST', body: fd });
    sid = body.session_id; summary = body.summary;
    $('render').src = 'data:image/png;base64,' + body.render_png_base64;
    $('status').textContent = `${summary.bodies.length} body, ${summary.faces.length} faces, ${summary.hole_groups.length} hole groups. Bbox ${summary.bbox_mm.x} × ${summary.bbox_mm.y} × ${summary.bbox_mm.z} mm.`;
    $('go').disabled = false; $('proposal').hidden = true; $('chat').innerHTML = ''; $('revise').disabled = true;
  } catch (err) { $('status').textContent = ''; $('err').textContent = err.message; }
};
async function submit(path, payload, label) {
  $('err').textContent = ''; $('go').disabled = true; $('revise').disabled = true;
  chat(label, 'user');
  try {
    const body = await call(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    chat(body.valid ? `Proposal ready (${body.attempts} attempt${body.attempts > 1 ? 's' : ''}).` : `Proposal has ${body.messages.length} validator issue(s). Revise or resubmit.`, body.valid ? '' : 'bad');
    show(body);
  } catch (err) {
    $('err').innerHTML = err.message + ' <button id="retry">Retry</button>';
    $('retry').onclick = () => submit(path, payload, label);
  }
  $('go').disabled = false;
}
$('go').onclick = () => submit(`/session/${sid}/propose`, { brief: $('brief').value }, $('brief').value);
$('revise').onclick = () => { const t = $('instruction').value; $('instruction').value = ''; submit(`/session/${sid}/revise`, { instruction: t }, t); };
$('download').onclick = () => { window.location = `/session/${sid}/download`; };
</script>
</body>
</html>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_web_app.py -q`
Expected: 13 passed

- [ ] **Step 7: Run it by hand once**

Run: `uvicorn src.web.app:app --reload` and open `http://127.0.0.1:8000`. Upload a STEP from `tests` fixtures (export one with cadquery if needed), enter a brief, confirm the proposal tables and colored render appear, then download the zip. Requires `ANTHROPIC_API_KEY` in the environment.

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest -q` → 116 passed, 1 skipped

```bash
git add src/web tests/test_web_app.py requirements.txt
git commit -m "feat(web): FastAPI app and single-page UI for the setup agent"
```

### Task 11: Eval Harness and the First Three Parts

**Files:**
- Create: `evals/__init__.py` (empty)
- Create: `evals/make_parts.py`
- Create: `evals/parts/bracket_l_4hole/{brief.md,reference.json}`
- Create: `evals/parts/tray_open/{brief.md,reference.json}`
- Create: `evals/parts/shaft_stepped/{brief.md,reference.json}`
- Create: `evals/run_evals.py`
- Create: `evals/results/.gitkeep`
- Test: `tests/test_evals_scoring.py`

**Interfaces:**
- Consumes: `GeometryAnalyzer`, `build_summary`, `run_pipeline`, `MaterialDatabase`, `playbook_hash`.
- Produces:
  - `make_parts.py`: `PARTS: dict[str, Callable[[], cq.Workplane]]` and `main()` writing `evals/parts/<name>/part.step` for every entry.
  - `run_evals.py`: `score_part(proposal: SetupProposal, reference: dict, db: MaterialDatabase) -> dict` with keys `load_cases, supports, loads, material, first_pass_valid, overall`; `resolve_reference_targets(reference, summary) -> dict` that turns label prefixes into face/hole-group ids; `run(part_names: list[str] | None, repeats: int = 3, propose_fn=propose) -> str` returning the markdown table and writing `evals/results/<date>_<playbook_hash>.md`. `python -m evals.run_evals` runs everything; `python -m evals.run_evals bracket_l_4hole --repeats 1` runs one.
- `reference.json` shape:

```json
{
  "material_family": "Steel",
  "supports": [{"type": "fixed", "targets": ["hole_group:4"], "alternatives": ["label:-Z face"]}],
  "loads": [{"type": "force", "targets": ["label:+X face"], "alternatives": ["label:+Z face"]}],
  "load_cases": [{"name": "static", "acceleration_g": [0, 0, -1]}, {"name": "shock", "acceleration_g": [0, 0, -20]}]
}
```

Target syntax: `label:<prefix>` matches the first summary face whose label starts with the prefix; `hole_group:<count>` matches the first hole group with that count; `id:f3` is a literal id. `alternatives` use the same syntax.

- [ ] **Step 1: Write the part generators**

```python
# evals/make_parts.py
"""cadquery scripts for the eval parts. Run: python -m evals.make_parts"""
from __future__ import annotations

from pathlib import Path
import cadquery as cq

PARTS_DIR = Path(__file__).parent / "parts"


def bracket_l_4hole():
    base = cq.Workplane("XY").box(120, 80, 8).faces(">Z").workplane() \
        .rect(90, 50, forConstruction=True).vertices().hole(9)
    upright = cq.Workplane("XZ").center(0, 40).box(120, 80, 8).translate((0, -36, 0))
    return base.union(upright)  # upright spans z 0..80, overlapping the 8 mm base so the union fuses


def tray_open():
    outer = cq.Workplane("XY").box(300, 200, 60)
    inner = cq.Workplane("XY").box(296, 196, 60).translate((0, 0, 2))
    tray = outer.cut(inner)
    return tray.faces("<Z").workplane().rect(260, 160, forConstruction=True).vertices().hole(6)


def shaft_stepped():
    return (cq.Workplane("YZ").circle(15).extrude(60)
            .faces(">X").workplane().circle(20).extrude(100)
            .faces(">X").workplane().circle(15).extrude(60))


PARTS = {
    "bracket_l_4hole": bracket_l_4hole,
    "tray_open": tray_open,
    "shaft_stepped": shaft_stepped,
}


def main(names=None):
    for name, builder in PARTS.items():
        if names and name not in names:
            continue
        out = PARTS_DIR / name
        out.mkdir(parents=True, exist_ok=True)
        cq.exporters.export(builder(), str(out / "part.step"))
        print("wrote", out / "part.step")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
```

Run: `python -m evals.make_parts` and confirm three `part.step` files exist.

- [ ] **Step 2: Write the briefs and references**

`evals/parts/bracket_l_4hole/brief.md`:

```markdown
Mild steel L-bracket bolted to a trailer frame through the four holes in its base. A 12 kg battery box sits on the upright's outer face and is strapped to it. Road use, so include a shock case.
```

`evals/parts/bracket_l_4hole/reference.json`:

```json
{
  "material_family": "Steel",
  "supports": [{"type": "fixed", "targets": ["hole_group:4"], "alternatives": ["label:-Z face"]}],
  "loads": [{"type": "force", "targets": ["label:-Y face", "label:+Y face"], "alternatives": ["label:Planar face"]}],
  "load_cases": [
    {"name": "static", "acceleration_g": [0, 0, -1]},
    {"name": "shock", "acceleration_g": [0, 0, -20]}
  ]
}
```

`evals/parts/tray_open/brief.md`:

```markdown
Aluminum open-top tray for loose tools, mounted on four standoffs through the holes in the floor. Holds about 15 kg spread over the floor. Vehicle mounted.
```

`evals/parts/tray_open/reference.json`:

```json
{
  "material_family": "Aluminum",
  "supports": [{"type": "fixed", "targets": ["hole_group:4"], "alternatives": ["label:-Z face"]}],
  "loads": [{"type": "pressure", "targets": ["label:+Z face"], "alternatives": ["label:Planar face"]}],
  "load_cases": [
    {"name": "static", "acceleration_g": [0, 0, -1]},
    {"name": "vertical", "acceleration_g": [0, 0, -3]}
  ]
}
```

`evals/parts/shaft_stepped/brief.md`:

```markdown
Steel stepped shaft supported in two bearings on the end journals. A belt pulley on the center section applies 2 kN radial load downward.
```

`evals/parts/shaft_stepped/reference.json`:

```json
{
  "material_family": "Steel",
  "supports": [
    {"type": "cylindrical", "targets": ["label:Cyl shaft #1"], "alternatives": ["label:-X face"]},
    {"type": "cylindrical", "targets": ["label:Cyl shaft #3"], "alternatives": ["label:+X face"]}
  ],
  "loads": [{"type": "bearing_load", "targets": ["label:Cyl shaft #2"], "alternatives": ["label:Cyl"]}],
  "load_cases": [{"name": "rated", "acceleration_g": [0, 0, 0]}]
}
```

Check the cylinder labels after generating the part: run `python -c "from src.geometry.analyzer import GeometryAnalyzer as G; [print(f.name) for f in G.analyze('evals/parts/shaft_stepped/part.step').faces]"` and adjust the `Cyl shaft #N` numbers so `#2` is the largest-diameter journal. Labels sort by area, so the center section is `#1` if it has the largest area; fix the reference to match what prints.

- [ ] **Step 3: Write the failing scoring tests**

```python
# tests/test_evals_scoring.py
import pytest
from evals.run_evals import score_part, resolve_reference_targets, _accel_match
from src.agent.schema import SetupProposal, GeometrySummary
from src.materials.database import MaterialDatabase


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


@pytest.fixture
def summary():
    return GeometrySummary.model_validate({
        "units": {"length": "mm", "force": "N", "mass": "kg"}, "bbox_mm": vec(100, 50, 20),
        "volume_mm3": 1.0, "estimated_mass_kg": 1.0,
        "bodies": [{"id": 0, "name": "b", "volume_mm3": 1.0, "centroid_mm": vec(0, 0, 0), "bbox_mm": vec(100, 50, 20)}],
        "faces": [
            {"id": "f0", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, 10), "normal": vec(0, 0, 1), "radius_mm": None, "label": "+Z face (top)"},
            {"id": "f1", "body_id": 0, "type": "planar", "area_mm2": 5000, "centroid_mm": vec(0, 0, -10), "normal": vec(0, 0, -1), "radius_mm": None, "label": "-Z face (bottom)"},
            {"id": "f2", "body_id": 0, "type": "cylindrical", "area_mm2": 200, "centroid_mm": vec(1, 1, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #1"},
            {"id": "f3", "body_id": 0, "type": "cylindrical", "area_mm2": 200, "centroid_mm": vec(9, 1, 0), "normal": None, "radius_mm": 4.0, "label": "Cyl hole #2"}],
        "hole_groups": [{"id": "hg1", "face_ids": ["f2", "f3"], "radius_mm": 4.0, "count": 2, "plane_normal": vec(0, 0, 1), "pattern": "linear"}],
        "symmetry_planes": [], "thin_walls": False})


@pytest.fixture
def reference():
    return {
        "material_family": "Steel",
        "supports": [{"type": "fixed", "targets": ["hole_group:2"], "alternatives": ["label:-Z face"]}],
        "loads": [{"type": "force", "targets": ["label:+Z face"], "alternatives": []}],
        "load_cases": [{"name": "static", "acceleration_g": [0, 0, -1]}, {"name": "shock", "acceleration_g": [0, 0, -20]}],
    }


def proposal(support_target="hg1", load_target="f0", accels=((0, 0, -1), (0, 0, -20)), material_id=1):
    return SetupProposal.model_validate({
        "materials": [{"body_id": 0, "material_id": material_id, "rationale": "x"}],
        "supports": [{"id": "s1", "target": support_target, "type": "fixed", "rationale": "x"}],
        "loads": [{"id": "l1", "target": load_target, "type": "force", "magnitude": 100.0, "direction": vec(0, 0, -1), "rationale": "x"}],
        "load_cases": [{"name": f"c{i}", "acceleration_g": vec(*a), "load_ids": ["l1"], "support_ids": ["s1"], "rationale": "x"} for i, a in enumerate(accels)],
        "mesh": {"global_size_mm": 4.0, "element_type": "Solid", "refinement": []},
        "assumptions": [], "questions": []})


def test_resolve_targets(summary, reference):
    r = resolve_reference_targets(reference, summary)
    assert r["supports"][0]["targets"] == ["hg1"] and r["supports"][0]["alternatives"] == ["f1"]
    assert r["loads"][0]["targets"] == ["f0"]


def test_perfect_score(summary, reference):
    s = score_part(proposal(), resolve_reference_targets(reference, summary), MaterialDatabase(), first_pass_valid=True)
    assert s == {"load_cases": 1.0, "supports": 1.0, "loads": 1.0, "material": 1.0, "first_pass_valid": 1.0, "overall": 1.0}


def test_alternative_support_counts(summary, reference):
    s = score_part(proposal(support_target="f1"), resolve_reference_targets(reference, summary), MaterialDatabase(), True)
    assert s["supports"] == 1.0


def test_wrong_material_family_and_missing_case(summary, reference):
    s = score_part(proposal(accels=((0, 0, -1),), material_id=5), resolve_reference_targets(reference, summary), MaterialDatabase(), False)
    assert s["material"] == 0.0 and s["load_cases"] == 0.5 and s["first_pass_valid"] == 0.0
    assert abs(s["overall"] - (0.5 + 1 + 1 + 0 + 0) / 5) < 1e-9


def test_accel_match_rules():
    assert _accel_match((0, 0, -1), (0, 0, -1.2))          # within 25 percent magnitude
    assert not _accel_match((0, 0, -1), (0, 0, -1.3))
    assert not _accel_match((0, 0, -1), (0, 0.5, -0.866))  # 30 degrees off
    assert _accel_match((0, 0, 0), (0, 0, 0))              # both zero counts as a match
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_evals_scoring.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'evals.run_evals'`

- [ ] **Step 5: Write the harness**

```python
# evals/run_evals.py
"""Score the proposal agent against hand-written references. Run: python -m evals.run_evals [part ...] [--repeats N]"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import date
from pathlib import Path

from src.agent.pipeline import run_pipeline
from src.agent.proposer import playbook_hash, propose
from src.agent.schema import GeometrySummary, SetupProposal
from src.agent.summary import build_summary
from src.geometry.analyzer import GeometryAnalyzer
from src.materials.database import MaterialDatabase

PARTS_DIR = Path(__file__).parent / "parts"
RESULTS_DIR = Path(__file__).parent / "results"
COLUMNS = ["load_cases", "supports", "loads", "material", "first_pass_valid", "overall"]
FAMILIES = {"Steel": "Steel", "Iron": "Steel", "Aluminum": "Aluminum", "Polymer": "Polymer",
            "Composite": "Polymer", "Titanium": "Titanium", "Copper": "Copper", "Nickel": "Steel",
            "Magnesium": "Aluminum", "Metal": "Steel", "Semi": "Polymer", "Concrete": "Polymer"}


def _resolve(token: str, summary: GeometrySummary) -> str | None:
    kind, _, value = token.partition(":")
    if kind == "id":
        return value if summary.target_exists(value) else None
    if kind == "label":
        for f in summary.faces:
            if f.label.startswith(value):
                return f.id
        return None
    if kind == "hole_group":
        for g in summary.hole_groups:
            if g.count == int(value):
                return g.id
        return None
    return None


def resolve_reference_targets(reference: dict, summary: GeometrySummary) -> dict:
    out = json.loads(json.dumps(reference))
    for key in ("supports", "loads"):
        for item in out.get(key, []):
            item["targets"] = [t for t in (_resolve(x, summary) for x in item.get("targets", [])) if t]
            item["alternatives"] = [t for t in (_resolve(x, summary) for x in item.get("alternatives", [])) if t]
    return out


def _accel_match(ref, got) -> bool:
    rm = math.sqrt(sum(c * c for c in ref))
    gm = math.sqrt(sum(c * c for c in got))
    if rm == 0.0 and gm == 0.0:
        return True
    if rm == 0.0 or gm == 0.0:
        return False
    if abs(gm - rm) > 0.25 * rm:
        return False
    cos = sum(a * b for a, b in zip(ref, got)) / (rm * gm)
    return cos >= math.cos(math.radians(15))


def _fraction_matched(ref_items: list[dict], got_targets: list[str]) -> float:
    if not ref_items:
        return 1.0
    hits = 0
    for item in ref_items:
        accepted = set(item["targets"]) | set(item["alternatives"])
        if accepted & set(got_targets):
            hits += 1
    return hits / len(ref_items)


def score_part(proposal: SetupProposal, reference: dict, db: MaterialDatabase, first_pass_valid: bool) -> dict:
    got_accels = [lc.acceleration_g.as_tuple() for lc in proposal.load_cases]
    ref_cases = reference.get("load_cases", [])
    case_hits = sum(1 for rc in ref_cases if any(_accel_match(tuple(rc["acceleration_g"]), g) for g in got_accels))
    load_cases = case_hits / len(ref_cases) if ref_cases else 1.0

    supports = _fraction_matched(reference.get("supports", []), [s.target for s in proposal.supports])
    loads = _fraction_matched(reference.get("loads", []), [l.target for l in proposal.loads])

    material = 0.0
    if proposal.materials:
        row = db.get_by_id(proposal.materials[0].material_id)
        if row and FAMILIES.get(row["category"], row["category"]) == reference.get("material_family"):
            material = 1.0

    fpv = 1.0 if first_pass_valid else 0.0
    overall = (load_cases + supports + loads + material + fpv) / 5
    return {"load_cases": load_cases, "supports": supports, "loads": loads, "material": material,
            "first_pass_valid": fpv, "overall": overall}


def _load_part(name: str):
    d = PARTS_DIR / name
    features, solids = GeometryAnalyzer.analyze_with_solids(str(d / "part.step"))
    summary = build_summary(features, [ns.body for ns in solids])
    brief = (d / "brief.md").read_text(encoding="utf-8").strip()
    reference = resolve_reference_targets(json.loads((d / "reference.json").read_text(encoding="utf-8")), summary)
    return summary, brief, reference


def run(part_names: list[str] | None = None, repeats: int = 3, propose_fn=propose) -> str:
    db = MaterialDatabase()
    names = part_names or sorted(p.name for p in PARTS_DIR.iterdir() if (p / "part.step").exists())
    rows = []
    for name in names:
        summary, brief, reference = _load_part(name)
        runs = []
        for i in range(repeats):
            result = run_pipeline(summary, brief, db, session_id=f"eval-{name}-{i}", propose_fn=propose_fn)
            runs.append(score_part(result.proposal, reference, db, result.attempts == 1 and result.valid))
        rows.append((name, runs))

    lines = [f"# Eval results {date.today().isoformat()} · playbook {playbook_hash()} · {repeats} runs per part", "",
             "| part | " + " | ".join(COLUMNS) + " |", "|---|" + "---|" * len(COLUMNS)]
    totals = {c: [] for c in COLUMNS}
    for name, runs in rows:
        cells = []
        for c in COLUMNS:
            vals = [r[c] for r in runs]
            m = statistics.mean(vals)
            spread = (max(vals) - min(vals)) if len(vals) > 1 else 0.0
            totals[c].append(m)
            cells.append(f"{m:.2f} ±{spread / 2:.2f}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("| **all** | " + " | ".join(f"**{statistics.mean(totals[c]):.2f}**" if totals[c] else "—" for c in COLUMNS) + " |")
    table = "\n".join(lines) + "\n"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{date.today().isoformat()}_{playbook_hash()}.md"
    out.write_text(table, encoding="utf-8")
    print(table)
    print("wrote", out)
    return table


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="*")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    run(args.parts or None, args.repeats)
```

- [ ] **Step 6: Run the scoring tests to verify they pass**

Run: `python -m pytest tests/test_evals_scoring.py -q`
Expected: 5 passed

- [ ] **Step 7: Run one live eval to prove the harness**

Run: `python -m evals.run_evals bracket_l_4hole --repeats 1` with `ANTHROPIC_API_KEY` set. Expected: a table prints with one row and a file appears in `evals/results/`. If `supports` scores 0, print the summary's labels and fix the reference tokens, not the scorer.

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest -q` → 121 passed, 1 skipped

```bash
git add evals tests/test_evals_scoring.py
git commit -m "feat(evals): scoring harness with three reference parts"
```

---

### Task 12: The Remaining Seven Eval Parts

**Files:**
- Modify: `evals/make_parts.py` (add seven builders to `PARTS`)
- Create: `evals/parts/<name>/{brief.md,reference.json}` for the seven names below

**Interfaces:**
- Consumes: `PARTS`, `main()` from Task 11; reference token syntax from Task 11.
- Produces: ten parts total, matching the spec mix: three brackets or mounts, two trays or enclosures, two frame sections or weldments, two shafts or pins, one lid or panel.

- [ ] **Step 1: Add the builders**

Append to `evals/make_parts.py` above `PARTS` and register each in the dict:

```python
def bracket_flat_2hole():
    return (cq.Workplane("XY").box(100, 40, 10)
            .faces(">Z").workplane().pushPoints([(-35, 0), (35, 0)]).hole(8))


def mount_pedestal():
    base = cq.Workplane("XY").box(120, 120, 10).faces(">Z").workplane() \
        .rect(90, 90, forConstruction=True).vertices().hole(10)
    post = cq.Workplane("XY").circle(20).extrude(80).translate((0, 0, 5))
    return base.union(post).faces(">Z").workplane().hole(12)


def enclosure_lidless():
    outer = cq.Workplane("XY").box(200, 150, 80)
    inner = cq.Workplane("XY").box(194, 144, 80).translate((0, 0, 3))
    box = outer.cut(inner)
    return box.faces("<Z").workplane().rect(170, 120, forConstruction=True).vertices().hole(5)


def frame_tube():
    """500 mm rectangular tube with 5 mm closed end plates; four holes in the -X plate."""
    outer = cq.Workplane("XY").box(500, 60, 40)
    inner = cq.Workplane("XY").box(490, 54, 34)
    tube = outer.cut(inner)
    return tube.faces("<X").workplane().rect(30, 15, forConstruction=True).vertices().hole(6)


def weldment_tee():
    beam = cq.Workplane("YZ").rect(50, 50).extrude(400).translate((-200, 0, 0))
    stub = cq.Workplane("XZ").rect(50, 50).extrude(150).translate((0, 0, 0))
    return beam.union(stub).faces("<X").workplane().rect(30, 30, forConstruction=True).vertices().hole(8)


def pin_clevis():
    return cq.Workplane("YZ").circle(10).extrude(120).faces(">X").workplane().circle(14).extrude(8)


def lid_flat():
    return (cq.Workplane("XY").box(300, 200, 6)
            .faces(">Z").workplane().rect(280, 180, forConstruction=True).vertices().hole(6)
            .faces(">Z").workplane().pushPoints([(0, 90), (0, -90)]).hole(6))
```

Register:

```python
PARTS = {
    "bracket_l_4hole": bracket_l_4hole,
    "bracket_flat_2hole": bracket_flat_2hole,
    "mount_pedestal": mount_pedestal,
    "tray_open": tray_open,
    "enclosure_lidless": enclosure_lidless,
    "frame_tube": frame_tube,
    "weldment_tee": weldment_tee,
    "shaft_stepped": shaft_stepped,
    "pin_clevis": pin_clevis,
    "lid_flat": lid_flat,
}
```

Run `python -m evals.make_parts` and open each STEP in the PyQt wizard or check `GeometryAnalyzer.analyze(...).faces` labels. If a builder fails in cadquery, simplify the shape rather than the brief.

- [ ] **Step 2: Write briefs and references**

For each part create `brief.md` and `reference.json`. Contents:

`bracket_flat_2hole`: brief "Aluminum flat bracket bolted at both holes to a bulkhead, with a 3 kg sensor hanging from the middle of its top face. Aircraft cabin, so use 9 g forward and 6 g down as crash cases." Reference: material Aluminum; supports fixed at `hole_group:2` (alt `label:-Z face`); loads force at `label:+Z face` (alt `label:Planar face`); cases `[0,0,-1]`, `[9,0,0]`, `[0,0,-6]`.

`mount_pedestal`: brief "Steel pedestal mount bolted to a deck through the four base holes. A 40 kg motor bolts to the top bore. Marine, 2 g heave and 1 g lateral." Reference: material Steel; supports fixed `hole_group:4` (alt `label:-Z face`); loads force at `label:+Z face` (alt `label:Cyl hole`); cases `[0,0,-1]`, `[0,0,-2]`, `[1,0,0]`.

`enclosure_lidless`: brief "Aluminum electronics enclosure, open top, mounted on four standoffs through the floor holes. 6 kg of boards and a transformer on the floor. Road vehicle." Reference: material Aluminum; supports fixed `hole_group:4`; loads pressure at `label:+Z face` (alt `label:Planar face`); cases `[0,0,-1]`, `[0,0,-3]`.

`frame_tube`: brief "Steel rectangular tube 500 mm long, bolted at one end plate through four holes to a chassis. Carries 1.5 kN downward at the free end from a hitch plate. Include a 1.5 times overload case." Reference: material Steel; supports fixed `hole_group:4` (alt `label:-X face`); loads force at `label:+X face` (alt `label:Planar face`); cases `[0,0,-1]` and `[0,0,-1.5]` (the overload case is the same load at 1.5 g, which the scorer can tell apart from 1 g).

`weldment_tee`: brief "Welded steel tee: 400 mm beam with a 150 mm stub, bolted at the beam's left end through four holes. A 2 kN downward load hangs from the end of the stub." Reference: material Steel; supports fixed `hole_group:4` (alt `label:-X face`); loads force at `label:-Y face` (alt `label:+Y face`); cases `[0,0,-1]`.

`pin_clevis`: brief "Steel clevis pin, 20 mm diameter, held at its head end and loaded in double shear by a 5 kN pull from a clevis on the shank." Reference: material Steel; supports fixed `label:+X face` (alt `label:Cyl shaft #2`); loads bearing_load `label:Cyl shaft #1` (alt `label:Cyl`); cases `[0,0,0]`.

`lid_flat`: brief "Aluminum lid 300 by 200 mm fastened around the edge with six screws. Sees 2 kPa wind pressure and a 500 N hand push at the center." Reference: material Aluminum; supports fixed `hole_group:6` (alt `hole_group:4`); loads pressure `label:+Z face` (alt `label:-Z face`); cases `[0,0,-1]`.

Write each `reference.json` in the exact shape shown in Task 11. After generating, print the labels for `pin_clevis` and `frame_tube` and correct the `Cyl shaft #N` and face tokens to what the analyzer actually emits.

- [ ] **Step 3: Run the full eval set once**

Run: `python -m evals.run_evals --repeats 1`. Expected: ten rows. Any part scoring 0 on supports or loads is almost always a reference token that does not resolve; fix the token, not the playbook, unless the proposal is genuinely wrong.

- [ ] **Step 4: Commit parts, references, and the first results file**

```bash
git add evals
git commit -m "feat(evals): ten reference parts and first full eval run"
```

### Task 13: Docker, Deployment, README

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `environment.yml`
- Modify: `README.md`
- Modify: `src/agent/render.py` (xvfb start on Linux)

**Interfaces:**
- Consumes: everything above.
- Produces: `docker build -t fea-agent .` and `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... fea-agent` serve the app on port 8000. README carries the three-sentence description, the architecture diagram, the latest eval table, three screenshots, and run instructions.

- [ ] **Step 1: Make the renderer start xvfb on Linux**

At the top of `src/agent/render.py`, after the imports:

```python
if os.name != "nt" and not os.environ.get("DISPLAY"):
    try:
        pv.start_xvfb()
    except Exception:
        pass  # a missing xvfb surfaces later as a render error with a clear message
```

- [ ] **Step 2: Write the conda environment and Dockerfile**

`environment.yml`:

```yaml
name: fea-agent
channels:
  - conda-forge
dependencies:
  - python=3.11
  - cadquery=2.7
  - pip
  - pip:
      - pydantic>=2.7
      - anthropic>=0.69
      - fastapi>=0.115
      - uvicorn>=0.30
      - python-multipart>=0.0.9
      - httpx>=0.27
      - pyvista>=0.45.0
      - Jinja2>=3.1.0
```

`Dockerfile`:

```dockerfile
FROM mambaorg/micromamba:1.5.8

USER root
RUN apt-get update && apt-get install -y --no-install-recommends xvfb libgl1 libxrender1 libxext1 libsm6 \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && micromamba clean --all --yes

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER src ./src
COPY --chown=$MAMBA_USER:$MAMBA_USER evals ./evals
COPY --chown=$MAMBA_USER:$MAMBA_USER pyproject.toml README.md ./

ENV PYVISTA_OFF_SCREEN=true
ENV CALLS_PER_SESSION=10
ENV SESSION_CAP_PER_HOUR=50
EXPOSE 8000
CMD ["micromamba", "run", "-n", "base", "uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`.dockerignore`:

```
.git
tests
docs
logs
dist
build
*.spec
__pycache__
```

- [ ] **Step 3: Build and smoke the container**

Run:

```bash
docker build -t fea-agent .
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY fea-agent
```

Open `http://localhost:8000`, upload `evals/parts/bracket_l_4hole/part.step`, submit its brief, download the zip. If the render fails inside the container, exec in and run `python -c "import pyvista as pv; pv.start_xvfb(); print('ok')"` to confirm xvfb is on the path.

- [ ] **Step 4: Deploy**

Pick Fly.io or Render. For Fly: `fly launch --no-deploy` (accept the generated `fly.toml`, internal port 8000), `fly secrets set ANTHROPIC_API_KEY=...`, `fly deploy`. Record the public URL in the README. Memory: request at least 2 GB; cadquery plus vtk needs it.

- [ ] **Step 5: Run the three-repeat eval and capture screenshots**

Run: `python -m evals.run_evals --repeats 3`. Save three screenshots to `docs/screenshots/`: the render with colored faces, the proposal tables, and the report HTML. Keep each under 400 KB.

- [ ] **Step 6: Write the README**

Replace `README.md` with the following, filling the eval table from the newest file in `evals/results/`:

```markdown
# FEA Setup Agent

Upload a STEP file, describe the part's job in a sentence or two, and get a complete ANSYS Static Structural setup: materials, supports, loads, load cases, and mesh, each with a rationale. A deterministic validator checks the proposal, a render shows which faces carry supports and loads, and the download is a Workbench journal plus an HTML report. An eval harness scores the agent against ten reference parts.

Live demo: <URL>

## Architecture

STEP → GeometryAnalyzer → Summary Builder (compact JSON) → Proposal Agent (Claude, structured output) → Validator (8 rules, one retry) → Adapter → Journal + Report. Renderer colors the chosen faces. FastAPI serves one page. See `docs/superpowers/specs/2026-09-03-fea-setup-agent-design.md`.

## Eval results

<paste the newest table from evals/results/>

Scores are 0 to 1. `load_cases`, `supports`, `loads` are the fraction of reference items matched (by id or an accepted alternative). `material` is family match. `first_pass_valid` is whether the validator passed without a retry. Three runs per part; ± is half the spread.

## Screenshots

![render](docs/screenshots/render.png)
![proposal](docs/screenshots/proposal.png)
![report](docs/screenshots/report.png)

## Run locally

    conda env create -f environment.yml && conda activate fea-agent
    export ANTHROPIC_API_KEY=...
    uvicorn src.web.app:app --reload

## Run with Docker

    docker build -t fea-agent .
    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... fea-agent

## Tests and evals

    python -m pytest -q
    python -m evals.run_evals --repeats 3

## The original desktop wizard

The PyQt6 wizard this grew out of still lives in `src/wizard` and runs with `python -m src.main`.
```

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest -q` → 121 passed, 1 skipped

```bash
git add Dockerfile .dockerignore environment.yml README.md src/agent/render.py docs/screenshots evals/results
git commit -m "feat: Docker image, deployment notes, README with eval table"
```

---

## Self-Review Notes

- **Spec coverage.** Summary Builder → Task 3. Playbook → Task 7. Schema → Task 1. Proposal Agent and logging → Task 7. Validator rules 1 to 8 → Task 2. Adapter and journal loop → Tasks 4 and 5. Renderer → Task 9. Report sections → Task 6. Web endpoints, caps, expiry, UI → Task 10. Eval harness, part mix, scoring, results files → Tasks 11 and 12. Docker and README → Task 13. Error handling rows in the spec map to the 400/413/404/409/429/502 responses in Task 10. Testing section: unit tests per component in each task; web tests with the model mocked; one live smoke test; evals separate.
- **Deviations** are listed under Global Constraints (Vec3 objects; one config with `load_cases`).
- **Type consistency.** `SetupProposal`, `GeometrySummary`, `Vec3.as_tuple()`, `target_face_ids`, `face_by_id`, `body_by_id` (added in Task 2), `ProposalResult`, `PipelineResult`, `LoadCaseBlock`, `to_config`, `render_png`, `run_pipeline(propose_fn=...)`, `app.state.propose_fn`: the same names are used in every task that consumes them.
- **Order of work for evenings without an API key or CAD kernel:** Tasks 1, 2, 4, 5, 6, 8 need neither. Tasks 3, 9, 10, 11, 12 need cadquery. Task 7's live test and Tasks 11 to 13 need the API key.

