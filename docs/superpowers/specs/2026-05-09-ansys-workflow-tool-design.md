# ANSYS Workflow Tool — Design Spec
Date: 2026-05-09

## Overview

A Windows desktop app that simplifies ANSYS Workbench/Mechanical simulation setup. The user uploads a CAD file, selects a simulation type, and steps through a 6-screen guided wizard. Smart defaults are pre-filled based on geometry analysis. The output is a Workbench journal file (`.wbjn`) that auto-applies all confirmed settings, plus an HTML settings summary.

**Target simulations:** Static Structural, Transient Structural, Thermal-Structural  
**Target geometry:** STEP, IGES, Parasolid (.x_t) CAD files  
**Target environment:** Windows 10/11, ANSYS Workbench/Mechanical

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI framework | Python 3.11+ with PyQt6 |
| CAD parsing | `cadquery` (OpenCASCADE backend) |
| Material database | SQLite (~50 materials) |
| Journal templating | Jinja2 |
| Settings summary output | HTML file (printable to PDF from browser) |
| Packaging | PyInstaller — single `.exe` for distribution |

---

## Architecture

Five components with clear boundaries:

```
CAD File
   │
   ▼
┌─────────────────────┐
│  Geometry Analyzer  │  Extracts features from STEP/IGES/x_t
└────────┬────────────┘
         │ geometry_features (dict)
         ▼
┌─────────────────────┐
│ Smart Defaults      │  Maps features + sim type → recommended settings
│ Engine              │
└────────┬────────────┘
         │ defaults (dict)
         ▼
┌─────────────────────┐     ┌──────────────────┐
│  Wizard UI          │ ←── │ Material Database│
│  (PyQt6, 6 steps)   │     │ (SQLite)         │
└────────┬────────────┘     └──────────────────┘
         │ confirmed_settings (dict)
         ▼
┌─────────────────────┐
│  Journal Generator  │  Produces .wbjn + settings_summary.html
└─────────────────────┘
```

---

## Components

### 1. Geometry Analyzer

Parses the uploaded CAD file using `cadquery` and returns a `geometry_features` dict consumed by the Smart Defaults Engine and the Wizard UI.

**Extracted features:**
- Bounding box dimensions (x, y, z in mm)
- Total volume and surface area
- Body count (single vs. assembly)
- Thin wall detection: flag any face pair with gap < L/20
- Hole detection: cylindrical interior surfaces, diameters + positions
- Symmetry plane detection: mirrors geometry across XY, XZ, YZ planes
- Fillet/sharp edge detection: edges with radius < 2mm flagged as stress concentrators

**Output dict keys:** `bbox`, `volume`, `surface_area`, `body_count`, `thin_walls`, `holes`, `symmetry_planes`, `sharp_edges`

---

### 2. Smart Defaults Engine

A pure function: `compute_defaults(geometry_features, simulation_type) → defaults_dict`

**Rules by geometry feature:**

| Feature | Default generated |
|---|---|
| Thin wall detected | Element type → Shell; warning shown |
| Holes present | Local mesh refinement at hole edges (diameter/8) |
| Symmetry plane found | Suggest symmetric BC; halve model option offered |
| Multiple bodies | Prompt to define contact between bodies |
| Sharp edges present | Local refinement at stress concentrators |
| Global element size | `min(bbox) / 50`, clamped to [0.5mm, 20mm] |

**Rules by simulation type:**

| Simulation type | Defaults added |
|---|---|
| Static Structural | Substeps: 1; large deflection: off; outputs: deformation, von Mises stress, safety factor |
| Transient Structural | End time: 1.0s; initial step: 0.01s; min step: 0.001s; max step: 0.1s; integration: Newmark |
| Thermal-Structural | Two-physics coupling; Page 4 (BCs) expands to show thermal BC types (Temperature, Convection) alongside structural ones; requires k and Cp in material; outputs add temperature, heat flux |

---

### 3. Wizard UI (PyQt6)

A `QWizard` with 6 pages. Each page has a sidebar showing completed steps and the current step highlighted. Navigation: Back / Next / Generate (final step).

**Page 1 — Geometry Upload**
- Drag-and-drop area + "Browse" button accepting `.step`, `.igs`, `.iges`, `.x_t`
- On file load: runs Geometry Analyzer in a background thread with a progress spinner
- Displays extracted feature summary once complete (bounding box, body count, detected features as tags)

**Page 2 — Simulation Type**
- Radio buttons: Static Structural / Transient Structural / Thermal-Structural
- Each option has a one-sentence description of when to use it
- Selection triggers Smart Defaults Engine to recompute defaults

**Page 3 — Material Assignment**
- Searchable list backed by SQLite material database
- Shows: E (Young's modulus), ν (Poisson's ratio), ρ (density), and conditionally α (thermal expansion), k (conductivity), Cp (specific heat)
- If multiple bodies detected: one material picker per body
- Default: Structural Steel

**Page 4 — Boundary Conditions**
- Two sections: Supports and Loads
- "Add" button per section opens a sub-dialog: select BC type → enter magnitude/direction → confirm
- Smart suggestions appear as dismissable hint cards (e.g., "Symmetry plane detected — add Frictionless Support?")
- Supported BC types:
  - Supports: Fixed, Frictionless, Displacement, Symmetric
  - Loads: Force, Pressure, Remote Force, Moment, Temperature (thermal), Convection (thermal)

**Page 5 — Mesh Settings**
- Global element size slider + numeric input (pre-filled from Smart Defaults)
- Refinement zones list (pre-filled from detected holes/edges): each entry shows face/edge and size
- Element type selector: Solid (Hex-dominant) / Shell / Auto
- Warning banner shown if thin wall detected and Solid is selected

**Page 6 — Solver Settings + Generate**
- Static: substep count, large deflection toggle
- Transient: end time, initial/min/max time step fields
- Thermal-Structural: same as appropriate type + coupling method
- Output requests checklist (checkboxes, pre-selected defaults shown)
- "Generate Journal + Summary" button: writes files to user-chosen output directory

---

### 4. Material Database (SQLite)

Single table `materials` with columns:
`id, name, category, E_GPa, nu, rho_kgm3, alpha_1e-6K, k_Wm-K, Cp_Jkg-K, yield_MPa, UTS_MPa, source`

~50 materials across categories: steels, aluminum alloys, titanium alloys, copper alloys, engineering polymers, composites (isotropic approximation).

Bundled as a read-only file inside the app package. Not user-editable in v1.

---

### 5. Journal Generator

Takes `confirmed_settings` dict and writes two files to the output directory:

**`simulation_setup.wbjn`**
- Valid ANSYS Workbench journal script (Python-based `.wbjn` format)
- Sections: geometry import, material assignment, mesh controls, BC application, solver settings, output requests
- Templated via Jinja2; one template per simulation type

**`settings_summary.html`**
- Self-contained HTML file, opens in any browser
- Sections mirror wizard pages: geometry info, simulation type, material, BCs, mesh, solver, outputs
- Each setting shows value + rationale (e.g., "Element size: 3.2 mm — L/50 rule applied to smallest bbox dimension 160 mm")
- Print-to-PDF produces a clean single-column document

---

## Data Flow (end-to-end)

1. User drops CAD file → `GeometryAnalyzer.analyze(path)` → `geometry_features`
2. User selects sim type → `SmartDefaultsEngine.compute(geometry_features, sim_type)` → `defaults`
3. Wizard pages pre-fill from `defaults`; user edits → `confirmed_settings` built incrementally
4. Final page: user clicks Generate → `JournalGenerator.write(confirmed_settings, output_dir)` → `.wbjn` + `.html`
5. User opens ANSYS Workbench → File → Run Script → selects `.wbjn` → project is configured

---

## Error Handling

- Unsupported file format: clear error on Page 1, prompt to re-upload
- Geometry parsing failure (corrupted file): error message with suggestion to re-export from CAD tool
- Missing required material property for sim type (e.g., k missing for thermal): warning on Page 3 before Next is enabled
- Journal write failure (permissions, disk full): error dialog with output path and retry option

---

## Out of Scope (v1)

- 3D geometry preview inside the app (use external CAD viewer)
- Custom material entry (read-only database)
- AI-assisted natural language input
- Results post-processing
- Cloud sync or collaboration
- APDL / Classic ANSYS support
