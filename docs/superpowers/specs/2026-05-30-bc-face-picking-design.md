# BC Page Face Picking — Design

**Date:** 2026-05-30
**Status:** Approved
**Component:** `src/wizard/pages/page_bcs.py`, `src/wizard/viewer.py`

## Problem

The Boundary Conditions page (Step 4) lets the user add supports and loads through
a modal dialog. The target face is chosen from a dropdown auto-populated with
auto-detected `FaceLabel` names, or typed freely. There is no way to click a face
in the 3D model to set the BC target, even though the `GeometryViewer` already
supports face picking (`set_face_picking(True)` + `face_picked(body_id, face_index)`).

Two facts shape the design:

1. **The BC page has no embedded viewer yet.** BCs are added through a modal
   `_BCDialog`. The Material page (Step 3) already embeds a `GeometryViewer` in a
   horizontal splitter — that pattern is the model to follow.
2. **Picked faces cannot be mapped to existing `FaceLabel` names.** The viewer
   emits `(body_id, face_index)` where `face_index` is the per-solid OCC face
   index. The `features.faces` list, by contrast, is built globally across all
   bodies, sorted by area, and truncated to `_MAX_LABELED_FACES` — it stores no
   `body_id` and no original face index. There is no shared key. So a picked face
   gets a **synthesized geometric name** rather than a reused label.

## Approach

**Flow:** Embed the viewer on the BC page (not in the dialog). Clicking a face
sets a "current target"; the next "+ Add" opens the dialog pre-filled with it.
This mirrors the Material page and keeps the dialog small.

**Target naming:** Synthesize a descriptive, unique name from the picked face's
centroid and area, e.g. `Face @ (12, 0, 34) · ~210 mm²`. Self-contained and
always works; the user re-creates it as a Named Selection in Mechanical.

## Components

### `src/wizard/viewer.py`

Two additions; the existing `face_picked(int, int)` signal contract is unchanged.

- **`format_face_target(centroid: tuple[float, float, float], area: float) -> str`**
  — module-level pure function. Builds the display string from a centroid and
  area. Rounds centroid components to integers and area to a sensible precision.
  Example output: `Face @ (12, 0, 34) · ~210 mm²`. Pure, unit-tested.

- **`GeometryViewer.face_summary(body_id: int, face_index: int) -> dict | None`**
  — selects the cells of `self._meshes[body_id]` whose per-cell `face_id` array
  equals `face_index`, and returns `{"centroid": (x, y, z), "area": float}`.
  Centroid is the mean of the selected cells' points; area is the summed cell
  area. Returns `None` if the body or face is unknown or the selection is empty.

### `src/wizard/pages/page_bcs.py`

- **`_BCDialog`** gains `preset_target: str = ""`. When non-empty, the editable
  target combo's current text is set to it (the auto-detected dropdown list and
  free typing remain available).

- **`BCsPage`**:
  - Layout becomes a horizontal `QSplitter`: left holds the existing
    Supports/Loads sections, Add/Remove buttons, the hint label, and a new
    read-only **"Picked face"** indicator; right holds an embedded
    `GeometryViewer`.
  - `initializePage` additionally calls
    `self._viewer.set_geometry(self.wizard().property("geometry_named_solids") or [])`
    and `self._viewer.set_face_picking(True)`.
  - New slot `_on_face_picked(body_id, face_index)`: calls
    `self._viewer.face_summary(...)`, formats the name via `format_face_target`,
    stores it in `self._current_target`, and updates the indicator label.
  - `_add` passes `preset_target=self._current_target` into `_BCDialog`.

## Data flow

```
click face → viewer.face_picked(body_id, face_index)
           → BCsPage._on_face_picked
           → viewer.face_summary(body_id, face_index) → {centroid, area}
           → format_face_target(...) → "Face @ (...) · ~A mm²"
           → self._current_target  +  indicator label
"+ Add"    → _BCDialog(preset_target=self._current_target)
           → user confirms → BoundaryCondition.target = that string
```

## Error handling

- `face_summary` returns `None` on unknown body/face or empty selection; the slot
  then leaves `_current_target` unchanged and the indicator shows a neutral
  "(no face picked)".
- If no geometry was loaded (e.g. analysis failed), the viewer is empty and
  picking simply yields nothing — the existing dropdown/free-type path is
  unaffected, so the page still works.

## Testing

- **Unit (TDD):** `format_face_target` — formatting, rounding, and the `~A mm²`
  shape. This is the only piece with pure logic worth locking down.
- **Manual smoke test:** load a real STEP file, open Step 4, click faces, confirm
  the indicator updates and the Add dialog pre-fills. `face_summary`'s mesh math
  is covered here because it needs a real tessellated body.

## Out of scope (YAGNI)

- Highlighting the picked face in the 3D view.
- Mapping picks back onto auto-detected `FaceLabel` names (deliberately avoided in
  favor of synthesized names).
