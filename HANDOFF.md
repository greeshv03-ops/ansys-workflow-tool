# ANSYS Workflow Tool — Session Handoff

## What This Project Is

A Windows desktop app (Python + PyQt6) that simplifies ANSYS Workbench/Mechanical simulation setup. Engineers upload a CAD file, step through a 6-page wizard, get smart defaults auto-filled from geometry analysis, and receive a Workbench journal file + HTML settings summary as output.

Supports: Static Structural, Transient Structural, Thermal-Structural  
CAD formats: STEP, IGES  
Output: `.wbjn` journal file + `settings_summary.html`

Full spec: `docs/superpowers/specs/2026-05-09-ansys-workflow-tool-design.md`  
Full plan: `docs/superpowers/plans/2026-05-09-ansys-workflow-tool.md`

---

## Current State (as of session end)

**Project directory:** `C:/Users/grees/ansys-workflow-tool`  
**Branch:** master  
**HEAD commit:** `6016b99 feat: add SmartDefaultsEngine`

### Completed Tasks ✅

| Task | Files | Commit |
|---|---|---|
| 1 — Scaffold | `requirements.txt`, `pyproject.toml`, `.gitignore`, all `__init__.py` | `01acf76` |
| 2 — Data models | `src/models.py`, `tests/test_models.py` | `466bdca` |
| 3 — Geometry Analyzer | `src/geometry/analyzer.py`, `tests/test_geometry_analyzer.py` | `3a8bc21` |
| 4 — Smart Defaults Engine | `src/defaults/engine.py`, `tests/test_defaults_engine.py` | `6016b99` |

**Installed dependencies (already in venv):**
- cadquery 2.7.0
- PyQt6 6.11.0
- Jinja2 3.1.6
- pytest 9.0.3

**Important fix from Task 3:** cadquery 2.7.0 uses `OCP.*` bindings, NOT `OCC.Core.*`. The plan's code uses the old import path in a few places — the actual committed code already has this corrected.

---

### Remaining Tasks (7 of 11)

Pick up from **Task 5** and continue in order.

---

## Task 5: Material Database

**Files to create:**
- `src/materials/database.py`
- `src/materials/materials.db` (generated, committed as bundled asset)
- `tests/test_material_database.py`

**Tests:**
```python
import pytest
from src.materials.database import MaterialDatabase

@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    MaterialDatabase.seed(path)
    return MaterialDatabase(path)

def test_search_returns_results(db):
    assert len(db.search("steel")) > 0

def test_search_case_insensitive(db):
    assert len(db.search("Aluminum")) > 0

def test_get_by_id_returns_material(db):
    m = db.get_by_id(db.search("structural steel")[0]["id"])
    assert "E_GPa" in m and m["E_GPa"] > 0

def test_get_by_id_missing_returns_none(db):
    assert db.get_by_id(99999) is None

def test_all_materials_have_required_fields(db):
    for m in db.search(""):
        assert m["nu"] > 0 and m["rho_kgm3"] > 0
```

**Implementation (`src/materials/database.py`):**
```python
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "materials.db"

SEED_DATA = [
    # (name, category, E_GPa, nu, rho_kgm3, alpha_1e6K, k_WmK, Cp_JkgK, yield_MPa, UTS_MPa, source)
    ("Structural Steel",        "Steel",    200.0, 0.30, 7850, 12.0,  60.5, 434,  250,  460, "ANSYS defaults"),
    ("Stainless Steel 316L",    "Steel",    193.0, 0.27, 7980, 16.0,  16.3, 500,  170,  485, "MatWeb"),
    ("High Strength Steel S690","Steel",    210.0, 0.30, 7850, 12.0,  50.0, 490,  690,  770, "EN 10025-6"),
    ("Cast Iron Gray",          "Iron",     110.0, 0.26, 7200, 11.0,  46.0, 544,    0,  179, "MatWeb"),
    ("Aluminum Alloy 6061-T6",  "Aluminum",  68.9, 0.33, 2700, 23.6, 167.0, 896,  276,  310, "ASM"),
    ("Aluminum Alloy 7075-T6",  "Aluminum",  71.7, 0.33, 2810, 23.6, 130.0, 960,  503,  572, "ASM"),
    ("Aluminum Alloy 2024-T3",  "Aluminum",  73.1, 0.33, 2780, 23.2, 121.0, 875,  345,  483, "ASM"),
    ("Aluminum 5052-H32",       "Aluminum",  70.3, 0.33, 2680, 23.8, 138.0, 880,  193,  228, "ASM"),
    ("Titanium Ti-6Al-4V",      "Titanium", 113.8, 0.342,4430,  8.6,   6.7, 560,  880,  950, "ASM"),
    ("Titanium Grade 2 CP",     "Titanium", 105.0, 0.37, 4510,  8.6,  16.0, 520,  275,  345, "ASM"),
    ("Copper C11000",           "Copper",   115.0, 0.34, 8900, 17.0, 388.0, 385,   69,  220, "MatWeb"),
    ("Brass C26000",            "Copper",   110.0, 0.34, 8530, 20.0, 120.0, 375,  310,  525, "MatWeb"),
    ("Magnesium AZ31B",         "Magnesium", 45.0, 0.35, 1770, 26.0,  96.0,1000,  200,  260, "ASM"),
    ("Inconel 718",             "Nickel",   200.0, 0.29, 8190, 13.0,  11.4, 435, 1034, 1240, "Special Metals"),
    ("HDPE",                    "Polymer",    0.8, 0.42,  960,150.0,   0.5,1900,   26,   37, "MatWeb"),
    ("Polycarbonate PC",        "Polymer",    2.4, 0.37, 1200, 68.0,   0.2,1250,   55,   65, "MatWeb"),
    ("Nylon 6 PA6",             "Polymer",    2.7, 0.39, 1140, 90.0,  0.25,1600,   60,   75, "MatWeb"),
    ("ABS",                     "Polymer",    2.3, 0.35, 1050, 90.0,  0.17,1400,   40,   50, "MatWeb"),
    ("PTFE Teflon",             "Polymer",    0.5, 0.46, 2200,135.0,  0.25,1000,   14,   31, "MatWeb"),
    ("Epoxy Resin",             "Polymer",    3.5, 0.38, 1250, 55.0,  0.17,1100,   60,   70, "MatWeb"),
    ("CFRP isotropic approx",   "Composite", 70.0, 0.10, 1600,  2.0,   5.0, 750,  500,  600, "Approx"),
    ("GFRP isotropic approx",   "Composite", 25.0, 0.25, 1900, 11.0,   0.3, 800,  150,  200, "Approx"),
    ("Concrete structural",     "Concrete",  30.0, 0.20, 2400, 12.0,   1.8, 880,    0,   30, "ACI 318"),
    ("Silicon",                 "Semi",     130.0, 0.28, 2329,  2.6, 148.0, 700, 7000, 7000, "MatWeb"),
    ("Tungsten",                "Metal",    411.0, 0.28,19300,  4.5, 173.0, 134, 1500, 1725, "MatWeb"),
    ("Tool Steel H13",          "Steel",    215.0, 0.30, 7750, 11.3,  24.0, 460, 1000, 1200, "MatWeb"),
    ("Steel high-temp 500C",    "Steel",    170.0, 0.30, 7850, 12.0,  40.0, 600,  100,  200, "EN 1993-1-2"),
    ("Bronze C63000",           "Copper",   117.0, 0.34, 7580, 18.0,  50.0, 376,  345,  655, "MatWeb"),
    ("Aluminum 1100-H14",       "Aluminum",  68.9, 0.33, 2710, 23.6, 222.0, 904,  115,  125, "ASM"),
    ("Lead",                    "Metal",     16.0, 0.44,11340, 29.0,  35.0, 128,   12,   17, "MatWeb"),
]


class MaterialDatabase:

    def __init__(self, db_path: str = str(DEFAULT_DB)):
        self._path = db_path

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def search(self, query: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM materials WHERE LOWER(name) LIKE ? ORDER BY name",
                (f"%{query.lower()}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, material_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM materials WHERE id = ?", (material_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def seed(db_path: str = str(DEFAULT_DB)) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT NOT NULL,
            E_GPa REAL NOT NULL, nu REAL NOT NULL, rho_kgm3 REAL NOT NULL,
            alpha_1e6K REAL, k_WmK REAL, Cp_JkgK REAL,
            yield_MPa REAL, UTS_MPa REAL, source TEXT)""")
        conn.execute("DELETE FROM materials")
        conn.executemany(
            "INSERT INTO materials (name,category,E_GPa,nu,rho_kgm3,alpha_1e6K,"
            "k_WmK,Cp_JkgK,yield_MPa,UTS_MPa,source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            SEED_DATA,
        )
        conn.commit()
        conn.close()
```

**After writing files:**
```bash
python -c "from src.materials.database import MaterialDatabase; MaterialDatabase.seed()"
pytest tests/test_material_database.py -v
git add src/materials/database.py src/materials/materials.db tests/test_material_database.py
git commit -m "feat: add MaterialDatabase with 30-material SQLite library"
```

---

## Task 6: Journal + Summary Generator

**Files to create:**
- `src/generator/journal.py`
- `src/generator/summary.py`
- `src/generator/templates/static_structural.wbjn.j2`
- `src/generator/templates/transient_structural.wbjn.j2`
- `src/generator/templates/thermal_structural.wbjn.j2`
- `src/generator/templates/settings_summary.html.j2`
- `tests/test_journal_generator.py`

See full implementation in `docs/superpowers/plans/2026-05-09-ansys-workflow-tool.md` — Task 6 section. It includes all Jinja2 template content, both generator classes, and 6 tests.

**Verify with:**
```bash
pytest tests/test_journal_generator.py -v
git add src/generator/ tests/test_journal_generator.py
git commit -m "feat: add JournalGenerator and SummaryGenerator with Jinja2 templates"
```

---

## Tasks 7–11: PyQt6 Wizard UI

These tasks build the 6-page wizard. No automated tests (Qt requires a running QApplication). Verify by smoke-testing: `python -m src.main` and walking through all 6 pages manually.

Full implementation code for all wizard pages is in the plan file. Implement in order:

| Task | Files | Commit message |
|---|---|---|
| 7 | `src/wizard/main_wizard.py`, `src/wizard/pages/page_upload.py` | `feat: add wizard shell and upload page` |
| 8 | `src/wizard/pages/page_simtype.py`, `page_material.py` | `feat: add simulation type and material wizard pages` |
| 9 | `src/wizard/pages/page_bcs.py` | `feat: add boundary conditions page` |
| 10 | `src/wizard/pages/page_mesh.py`, `page_solver.py` | `feat: add mesh and solver pages with generate button` |
| 11 | `src/main.py`, `ansys_tool.spec` | `feat: add app entry point and PyInstaller packaging` |

**Final smoke test (Task 11):**
1. `python -m src.main`
2. Drop a STEP file → confirm bbox/feature tags appear
3. Select Static Structural → Next
4. Search "aluminum 6061" → select → Next
5. Add Fixed support + Force 500N → Next
6. Confirm mesh defaults pre-filled → Next
7. Click Generate → pick output folder → confirm `.wbjn` + `settings_summary.html` created

---

## Key Architecture Notes

- `src/models.py` — all shared types. Import from here everywhere.
- `wizard.setProperty("key", value)` / `wizard.property("key")` — how wizard pages share state (geometry_features, sim_type, smart_defaults, material_id, mesh_settings, solver_settings, boundary_conditions)
- `SmartDefaultsEngine.compute()` is called in `SimTypePage._on_select()` and result stored as `wizard.property("smart_defaults")` — mesh and solver pages read from this
- cadquery uses **OCP bindings** (`from OCP.xxx import ...`), NOT `OCC.Core.*` — this is already fixed in committed code but watch for it if writing new OCC calls
- `materials.db` is a committed bundled asset (read-only at runtime)

---

## How to Resume

In your new session, tell Claude Code:

> "I'm working on the ANSYS Workflow Tool at `C:/Users/grees/ansys-workflow-tool`. Read `HANDOFF.md` and the plan at `docs/superpowers/plans/2026-05-09-ansys-workflow-tool.md`, then continue implementing from Task 5."
