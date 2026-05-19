# ANSYS Workflow Tool — Session Handoff

## What this project is

A Windows desktop app (Python + PyQt6) that simplifies ANSYS Workbench/Mechanical
simulation setup. Drop a CAD file, step through a 6-page wizard with a live 3D
viewer, get smart defaults auto-filled from geometry analysis, and receive a
Workbench journal file + HTML settings summary as output.

- Supported sim types: Static Structural, Transient Structural, Thermal-Structural
- Supported CAD: STEP (`.step`, `.stp`), IGES (`.iges`, `.igs`)
- Output: `.wbjn` Workbench journal + `settings_summary.html`

## Where things live

- Project root: `C:/Users/grees/ansys-workflow-tool`
- Branch: `master`
- Spec: `docs/superpowers/specs/2026-05-09-ansys-workflow-tool-design.md`
- Plan: `docs/superpowers/plans/2026-05-09-ansys-workflow-tool.md`
- Run: `python -m src.main`
- Tests: `pytest -q` — 40 tests pass

## Current state

All 11 plan tasks complete; the post-plan UX upgrades for the 3D viewer are
also done. Latest commit: `5b76f38 feat: distinct part colors, hover labels,
view presets, explode slider, visibility list`.

### Wizard pages

| # | Page | What it does |
|---|------|--------------|
| 1 | Upload | Drop a STEP/IGES → threaded analyzer; 3D viewer shows the result |
| 2 | Sim Type | Pick Static / Transient / Thermal; computes smart defaults |
| 3 | Materials | Per-body material assignment with body list, material list, embedded 3D viewer |
| 4 | Boundary Conditions | Add/remove supports & loads. Face name dropdown auto-populated from geometry. **Face picking from viewer still TODO** |
| 5 | Mesh | Smart defaults pre-filled (element size, type, refinement zones) |
| 6 | Solver | Time integration, output requests, **Generate** button writes `.wbjn` + `.html` |

### Geometry pipeline

`GeometryAnalyzer.analyze_with_solids(path)` returns
`(GeometryFeatures, list[NamedSolid])` in a single STEP parse:

- Uses `STEPCAFControl_Reader` to walk the assembly tree and recover real
  part names (`A-Frame-Mount-Plate-body`, `...Socket Head Screw`, etc.)
- Accumulates `TopLoc_Location` through nested assemblies so every instance
  lands at its world position (62-body test file now positions correctly)
- Skips expensive Volume/Area integrations on assemblies (`body_count > 3`)
- Uses analytical `Bnd_Box` instead of mesh-based bounding boxes
- 62-body assembly: **~5s** (was ~460s pre-optimization)

### 3D Viewer (`src/wizard/viewer.py`)

`GeometryViewer` is a QWidget built on `pyvistaqt.QtInteractor`:

- One VTK actor per body so picking dispatches on body identity
- Per-cell `face_id` baked in at tessellation time for face picking
- Tessellation refined: `face.toVtkPolyData(0.1, 0.2)`
- Colors:
  - Distinct color per unique STEP part name (deterministic md5 → 12-entry palette)
  - Recolored by material category when assigned (steel=gray, aluminum=silver…)
  - Highlight color (orange) for the currently-selected body
- Toolbar: `Iso / Top / Front / Right / Fit` view presets + `Explode` slider
  (0..100 → 0..2× distance-from-assembly-centroid)
- Visibility list (left side): one checkbox per part group; toggling hides
  every instance of that group
- Hover overlay: `vtkPropPicker` resolves the actor under the cursor, the
  body's part name shows in a 2D text actor at lower-left
- Signals: `body_picked(int)`, `face_picked(int, int)`

### Data model (`src/models.py`)

- `Body(id, name, volume, centroid, bbox)`
- `BodyMaterial(body_name, body_ids, material_id, material_name)`
- `GeometryFeatures` now carries `bodies: list[Body]` and `faces: list[FaceLabel]`
- `SimulationConfig.body_materials: list[BodyMaterial]` (replaced single
  `material_id`/`material_name`)

### Materials

`MaterialDatabase` is SQLite-backed (`src/materials/materials.db`) with 30
seeded entries across 12 categories. Search/filter and `get_by_id` only.

### Templates

- `src/generator/templates/static_structural.wbjn.j2`
- `src/generator/templates/transient_structural.wbjn.j2`
- `src/generator/templates/thermal_structural.wbjn.j2`
- `src/generator/templates/settings_summary.html.j2` — renders per-body
  material assignments

## What still needs doing

1. **Per-body material output in the `.wbjn` templates.** The summary HTML
   already shows per-body materials, but the three journal templates still
   emit a single material assignment. They need to loop over
   `config.body_materials` and emit one assignment block per body group.
2. **Face picking on the BC page.** The BC dialog accepts face names from a
   dropdown auto-populated for single-body parts, but there's no
   "click a face in the viewer → fill the BC target" wiring yet. The viewer
   already supports it (`set_face_picking(True)` + `face_picked` signal); just
   need to embed the viewer in `page_bcs.py` and connect the signal.
3. **PyInstaller spec update.** `ansys_tool.spec` may need `pyvista`/`vtk`
   hidden imports + data files when building the standalone exe.
4. **Smoke test the full flow end-to-end** with a real CAD file (no automated
   GUI tests exist because Qt requires a `QApplication`).

## Known issues / quirks

- **Window may open behind other apps** when launched in background — Alt+Tab
  to find "ANSYS Simulation Setup Wizard".
- **First STEP load is slow** (3–8s for a 5MB assembly) because of the parser;
  feedback in the upload page is a progress bar + "Analyzing geometry…" text.
- **`cadquery` `BoundingBox` is mesh-based and slow** on compounds; analyzer
  uses the analytical `Bnd_Box` path everywhere it can.
- **`OCP.OCP.X` vs `OCP.X` imports** — the older `OCP.OCP.*` paths used to
  appear in `_detect_holes` but were silently failing; all OCP imports now use
  the canonical single-prefix path.

## Startup / shutdown: VTK + Qt OpenGL handling

`src/main.py` performs two OpenGL setup steps that are essential — do not
remove or reorder them:

1. **Before `QApplication`**: a default `QSurfaceFormat` (OpenGL 3.2 Core,
   24-bit depth, 8-bit stencil) is installed and `AA_ShareOpenGLContexts` is
   set. Without this, the two embedded `QtInteractor`s (one in `page_upload`
   and one in `page_material`) negotiate incompatible pixel formats vs. Qt's
   widget HDCs and `wglMakeCurrent` fails with `ERROR_INCORRECT_PIXEL_TYPE`
   (2004) on every paint.
2. **`app.aboutToQuit`** is connected to `vtkObject.GlobalWarningDisplayOff()`.
   This silences a known VTK destructor-order issue: `vtkWin32OpenGLRenderWindow`
   calls `wglMakeCurrent` during its destructor after Qt has already torn down
   the HDC, then mis-formats the resulting `DWORD` error code through
   `FormatMessageW` and prints garbled Unicode to stderr. The errors are
   cosmetic — there is nothing left to render — but they look alarming.
   Silencing only at quit time keeps real runtime VTK warnings visible.

**Note for future sessions**: an earlier memory entry (May 13, 2026)
labelled this as "OpenGL Rendering Failure / driver issue" and called the
GUI blocked. That diagnosis was wrong. The GPU and drivers are fine
(verified via standalone VTK probe — OpenGL 4.6 Compatibility on the AMD
Radeon 780M); the noise was cosmetic shutdown spam and the wizard always
ran. Fixed 2026-05-18.

## How to resume in a new session

In your new Claude Code session, tell Claude:

> "I'm working on the ANSYS Workflow Tool at `C:/Users/grees/ansys-workflow-tool`.
> Read `HANDOFF.md`, then continue from the 'What still needs doing' list."
