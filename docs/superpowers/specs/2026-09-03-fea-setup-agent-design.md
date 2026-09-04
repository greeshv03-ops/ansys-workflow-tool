# FEA Setup Agent — Design Spec
Date: 2026-09-03

## Overview

A web-deployed agent that takes a STEP file and a plain-English brief describing the part's job, and proposes a complete Static Structural simulation setup: materials, supports, loads, load cases, and mesh, each with a one-line rationale. A deterministic validator checks the proposal, the existing journal generator writes the ANSYS Workbench journal, and a rendered image shows which faces carry supports and loads. An eval harness scores the agent against ten hand-authored reference setups and reports a number.

**Purpose:** a portfolio project demonstrating an agentic workflow built into a real engineering tool, with measured accuracy. Primary user is the author; secondary user is a hiring manager running the public demo on a sample part in under five minutes.

**Reuses:** the geometry analyzer, materials database, smart-defaults engine, journal generator, and summary generator from the existing ANSYS Workflow Tool (spec 2026-05-09).

**Sim type in scope:** Static Structural only.

**Time budget:** roughly 40 hours over eight weeks. Every scope decision below defers to that.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Backend | FastAPI, uvicorn |
| UI | One static HTML page with vanilla JS, served by FastAPI |
| CAD parsing | `cadquery` (existing analyzer) |
| Rendering | `pyvista` off-screen (carried over from the PyQt viewer's tessellation code) |
| Model | Claude Opus 5 (`claude-opus-5`) via the Anthropic Python SDK; structured output through `client.messages.parse()` with a Pydantic schema; adaptive thinking on |
| Schema and validation | Pydantic v2 |
| Journal templating | Jinja2 (existing) |
| Evals | pytest module that writes a markdown results table |
| Packaging | Docker image with the CAD kernel baked in |
| Hosting | Any container host with a public URL (Fly.io or Render); API key from an environment variable |

---

## Architecture

```
STEP upload
   │
   ▼
┌───────────────────────┐
│ Geometry Analyzer     │  existing; returns GeometryFeatures + bodies + faces
└──────────┬────────────┘
           │
           ▼
┌───────────────────────┐
│ Summary Builder       │  NEW: compact JSON for the prompt; hole grouping;
│                       │  small-face pruning; stable face/hole-group IDs
└──────────┬────────────┘
           │ geometry_summary (JSON)          brief (text)       playbook (markdown)
           ▼                                   │                   │
┌────────────────────────────────────────────────────────────────────┐
│ Proposal Agent                                                     │
│ NEW: one structured-output call → SetupProposal (Pydantic)         │
└──────────┬─────────────────────────────────────────────────────────┘
           │ proposal
           ▼
┌───────────────────────┐   fail (≤1 retry)   ┌─────────────────────┐
│ Validator             │ ──────────────────► │ Proposal Agent      │
│ NEW: deterministic    │                     │ (revision call)     │
└──────────┬────────────┘                     └─────────────────────┘
           │ valid proposal
           ├──────────────────────────────┐
           ▼                              ▼
┌───────────────────────┐      ┌───────────────────────┐
│ Adapter → SimulationConfig │ │ Renderer              │
│ NEW: proposal → existing   │ │ NEW: PNG with colored │
│ dataclasses, one system    │ │ support/load faces    │
│ per load case              │ └───────────────────────┘
└──────────┬────────────┘
           ▼
┌───────────────────────┐
│ Journal + Report      │  existing generators; template extended for
│ Generators            │  multiple load cases and rationale/assumptions
└───────────────────────┘
```

All of this sits behind a FastAPI app with in-memory sessions. Chat revisions re-enter at the Proposal Agent with the current proposal and the user's instruction.

---

## Components

### 1. Summary Builder (`src/agent/summary.py`)

Input: `GeometryFeatures` and the body list from `GeometryAnalyzer.analyze_with_solids()`.
Output: `GeometrySummary` (Pydantic), serialized to JSON for the prompt.

Contents:

- `units`: always `{"length": "mm", "force": "N", "mass": "kg"}`; stated explicitly in the JSON.
- `bbox_mm`, `volume_mm3`, `estimated_mass_kg` (volume times a placeholder density of 7850 kg/m³, labeled as an estimate before material assignment).
- `bodies[]`: `id`, `name`, `volume_mm3`, `centroid_mm`, `bbox_mm`.
- `faces[]`: `id` (string, stable: `f{index}` in analyzer order), `body_id`, `type` (`planar`, `cylindrical`, `other`), `area_mm2`, `centroid_mm`, `normal` (planar only), `radius_mm` (cylindrical only), `label` (the analyzer's existing descriptive label, e.g. `top face`, `mounting hole`).
- `hole_groups[]`: `id` (`hg{index}`), `face_ids[]`, `radius_mm`, `count`, `plane_normal`, `pattern` (`linear`, `rectangular`, `circular`, `irregular`). Grouping rule: cylindrical faces with radius within 2 percent of each other and axes parallel within 5 degrees, whose centers lie on a common plane within 0.5 mm. A group needs at least two holes.
- `symmetry_planes[]` and `thin_walls` pass through from the analyzer.

Pruning: faces with area below 0.1 percent of total surface area are dropped from the summary unless they belong to a hole group. Hard cap of 200 faces after pruning; parts above the cap are rejected at upload with a clear message.

### 2. Playbook (`src/agent/playbook.md`)

A markdown reference the author writes and maintains. Loaded at startup and placed in the system prompt after the schema description. Sections:

- **Geometry classes and their standard load-case sets**: brackets and mounts, trays and enclosures, frame sections and weldments, shafts and pins, lids and panels. For each: typical supports, typical loads, standard g-factors for static, dynamic, and shock cases, and which standards are commonly cited (for example ECE R100 and SAE J2380 for battery hardware, ISO 16750-3 for vehicle-mounted components).
- **Support selection**: how to pick faces that constrain the part the way the real assembly does; the overconstraint trap; when to use a cylindrical support versus a fixed support on hole faces; symmetry use.
- **Load application**: force versus pressure versus remote load; direction conventions relative to the summary's axes; body accelerations for inertial cases.
- **Mesh sizing**: global size as a fraction of the smallest characteristic dimension; refinement at holes, fillets, and sharp corners; when shell elements apply.
- **Material selection**: mapping brief keywords to database families (structural steel, aluminum 6061 and 7075, stainless, polymers).
- **Assumptions and questions**: the model must list every assumption it made where the brief was silent, and one to three questions it would ask the engineer.

The playbook is versioned in git. Eval results reference the playbook commit hash.

### 3. Proposal Schema (`src/agent/schema.py`)

`SetupProposal` (Pydantic, used as the structured-output schema):

```
SetupProposal
  materials: list[MaterialAssignment]
      body_id: int
      material_id: int          # must exist in MaterialDatabase
      rationale: str
  supports: list[Support]
      id: str                   # s1, s2, ...
      target: str               # face id or hole-group id
      type: Literal["fixed", "frictionless", "cylindrical", "displacement"]
      rationale: str
  loads: list[Load]
      id: str                   # l1, l2, ...
      target: str               # face id or hole-group id
      type: Literal["force", "pressure", "remote_force", "bearing_load"]
      magnitude: float          # N or MPa per type
      direction: tuple[float, float, float]   # unit vector in summary axes
      rationale: str
  load_cases: list[LoadCase]
      name: str
      acceleration_g: tuple[float, float, float]
      load_ids: list[str]
      support_ids: list[str]
      rationale: str
  mesh: MeshProposal
      global_size_mm: float
      element_type: Literal["Solid", "Shell", "Auto"]
      refinement: list[Refinement]
          target: str           # face id or hole-group id
          size_mm: float
          reason: str
  assumptions: list[str]
  questions: list[str]
```

The model returns the whole proposal every time, including on revisions. No partial updates.

### 4. Proposal Agent (`src/agent/proposer.py`)

One function: `propose(summary, brief, playbook, prior=None, feedback=None, instruction=None) -> SetupProposal`.

- System prompt: role statement, the units convention, the schema explanation, then the playbook. This prefix is stable across calls so it caches.
- User message: the geometry summary JSON, then the brief. On revision calls, also the prior proposal JSON, the validator messages if any, and the user's instruction.
- Call: `client.messages.parse()` with `SetupProposal` as the output format, `claude-opus-5`, adaptive thinking, `max_tokens` 16000, server-side refusal fallbacks enabled.
- Every call logs to `logs/proposals.jsonl`: timestamp, session id, model, prompt token count, output token count, cache read tokens, latency, playbook commit hash, brief, summary hash, the proposal, and validator outcome. This log is the observability story and the eval input.

Error handling: API errors surface to the UI as a plain message with a retry button. No silent retries beyond the SDK's own two.

### 5. Validator (`src/agent/validator.py`)

`validate(proposal, summary, materials_db) -> list[str]`. Empty list means valid. Rules, each producing a specific message:

1. Every body has exactly one material assignment; every `material_id` exists in the database.
2. At least one support exists; every support and load `target` exists in `summary.faces` or `summary.hole_groups`.
3. No target carries both a support and a load.
4. Every load case references at least one existing load id or has a nonzero acceleration; every referenced support id exists.
5. Magnitude bands: acceleration components at most 30 g in absolute value; force magnitudes below 1e6 N; pressures below the assigned material's yield strength.
6. Mesh global size between 1 percent and 10 percent of the largest bounding-box dimension; every refinement size smaller than the global size.
7. Overconstraint: fixed supports must not cover every face of any body; total fixed-support area must be below 50 percent of that body's surface area.
8. Load direction vectors have unit length within 1 percent.

Flow: proposal → validate. If messages exist, call `propose()` once more with the messages as feedback. If the second attempt still fails, return it to the UI flagged invalid, with the messages shown. No third automatic attempt.

### 6. Adapter (`src/agent/adapter.py`)

Converts a valid `SetupProposal` plus the analyzer's `GeometryFeatures` into the existing `SimulationConfig`, one per load case, so the existing generators run unchanged where possible.

- Face and hole-group ids resolve to the analyzer face names the journal template already uses for named selections.
- Hole-group targets expand to their member faces.
- Accelerations become a `BoundaryCondition` of type `acceleration` with the g-vector converted to mm/s².

Journal template change: `static_structural.wbjn.j2` gains a loop so one journal file contains one Static Structural system per load case, all sharing geometry, materials, and mesh. This is the only template edit.

### 7. Renderer (`src/agent/render.py`)

Off-screen pyvista render of the tessellated part. Face ids from the proposal color support faces blue and load faces orange; everything else light gray. Isometric view, 1200 by 900 PNG, returned as base64 to the UI. Tessellation code is lifted from `src/wizard/viewer.py`; the Qt dependency is not imported.

### 8. Report (`src/generator/summary.py`, extended)

The existing settings summary HTML gains three sections: load-case table, rationale per row, and the assumptions and questions lists. Downloaded alongside the journal as a zip.

### 9. Web App (`src/web/app.py`, `src/web/static/index.html`)

Endpoints:

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/session` | STEP file (multipart, ≤20 MB) | `session_id`, geometry summary, base render |
| POST | `/session/{id}/propose` | `{brief}` | proposal, validator messages, render |
| POST | `/session/{id}/revise` | `{instruction}` | proposal, validator messages, render |
| GET | `/session/{id}/download` | none | zip of `.wbjn` and report HTML |

Sessions live in a dict with a one-hour expiry and hold the analyzer output, the current proposal, and the chat history. Cap: 10 proposal or revision calls per session, 50 sessions per hour per process. Exceeding a cap returns a plain message.

UI layout: left column with upload, brief text area, and chat history; right column with the render, the proposal as tables (materials, supports, loads, load cases, mesh) with rationale in the last column, the assumptions and questions lists, and the download button. No framework, no build step.

### 10. Eval Harness (`evals/`)

Structure:

```
evals/
  parts/
    bracket_l_4hole/
      part.step
      brief.md
      reference.json      # SetupProposal shape + `alternatives` per field
    ...(10 parts)
  run_evals.py            # pytest module; also runnable as a script
  results/
    2026-09-20_abc1234.md # one file per run, named by date and playbook hash
```

Part mix: three brackets or mounts, two trays or enclosures, two frame sections or weldments, two shafts or pins, one lid or panel. Sources: the author's own Onshape models exported to STEP, plus permissively licensed public models. Each part's `reference.json` is authored by hand, with an `alternatives` block listing other acceptable targets for supports and loads.

Scoring per part, each in the range 0 to 1:

- `load_cases`: fraction of reference load cases matched. A match is an acceleration vector within 25 percent in magnitude and within 15 degrees in direction.
- `supports`: fraction of reference supports whose target matches the proposal by id or by an accepted alternative.
- `loads`: same rule for loads.
- `material`: 1 if the family matches (steel, aluminum, stainless, polymer), else 0.
- `first_pass_valid`: 1 if the validator passed on the first attempt.

Overall score per part is the mean of the five. Run score is the mean across parts. Each invocation runs every part three times and reports mean and spread per column. Results are committed to the repo. The README embeds the latest table.

---

## Data Flow, End to End

1. User uploads a STEP. Analyzer runs in a thread. Summary Builder produces the JSON. Renderer produces a base render. UI shows the part and enables the brief box.
2. User types a brief and submits. Proposal Agent runs. Validator runs. If needed, one revision call. UI shows the proposal, messages, and the colored render.
3. User optionally types a revision. Same path with `instruction` set.
4. User downloads. Adapter builds one `SimulationConfig` per load case. Journal Generator writes the `.wbjn`. Summary Generator writes the report. Both are zipped and returned.

---

## Error Handling

- Unsupported or unreadable CAD: upload returns a plain message; no session is created.
- Part over the 200-face cap or 20 MB: rejected at upload with the limit stated.
- Model API error: surfaced to the UI with a retry button; logged.
- Validator failure after retry: proposal shown, marked invalid, messages listed; download disabled until a valid proposal exists.
- Session expiry: UI receives 404 and prompts a fresh upload.

---

## Testing

- Unit tests for Summary Builder (hole grouping on synthetic geometry, pruning, cap), Validator (one test per rule, pass and fail), Adapter (proposal to config round trip, hole-group expansion), and the journal template loop (rendered journal contains N systems).
- Renderer test asserts a PNG is produced and that colored pixels exist for a known face id.
- Web tests use FastAPI's test client with the model call mocked; cover upload, propose, revise, download, caps, and expiry.
- Proposal Agent has one live smoke test, marked to skip without an API key.
- Evals are separate from unit tests and run on demand.

Existing 46 tests must keep passing.

---

## Deployment

Single Dockerfile based on a conda or micromamba image so cadquery installs cleanly. Runs uvicorn on the container port. Environment variables: `ANTHROPIC_API_KEY`, `SESSION_CAP_PER_HOUR`, `CALLS_PER_SESSION`. No persistent volume. Logs go to stdout and to the proposals log file inside the container; the log is for local runs and evals, not production retention.

README carries: what it does in three sentences, the architecture diagram, the latest eval table, three screenshots, and how to run locally and with Docker.

---

## Out of Scope

Listed so nothing creeps back in:

- The PyQt wizard (kept in the repo, not used by the new path)
- Interactive face picking in a 3D viewer
- Transient and thermal sim types
- Running a solver or reading results
- Multi-user accounts, authentication, persistent storage
- IGES input for the agent path (STEP only)

---

## Build Order (for the implementation plan)

1. Schema, Validator, and their tests. No model calls yet.
2. Summary Builder and tests.
3. Adapter, journal template loop, and tests.
4. Proposal Agent with the first draft of the playbook, plus the live smoke test.
5. Renderer.
6. Web app and UI.
7. Eval set: three parts first to prove the harness, then the remaining seven.
8. Docker, deployment, README.

Steps 1 through 3 are the ones the author can finish without an API key or the CAD kernel installed on a new machine, which matters for evenings-only work.
