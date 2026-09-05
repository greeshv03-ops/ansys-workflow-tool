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
    strength_by_body = {}
    strength_type = {}  # "yield" or "UTS"
    for m in p.materials:
        row = db.get_by_id(m.material_id)
        if row:
            yield_val = row.get("yield_MPa")
            uts_val = row.get("UTS_MPa")
            if yield_val and yield_val > 0:
                strength_by_body[m.body_id] = float(yield_val)
                strength_type[m.body_id] = "yield"
            elif uts_val and uts_val > 0:
                strength_by_body[m.body_id] = float(uts_val)
                strength_type[m.body_id] = "UTS"
    for ld in p.loads:
        if ld.type == "pressure":
            face_ids = s.target_face_ids(ld.target)
            body_id = s.face_by_id(face_ids[0]).body_id if face_ids else None
            limit = strength_by_body.get(body_id)
            if limit is not None and ld.magnitude >= limit:
                if strength_type[body_id] == "yield":
                    out.append(f"rule5: load {ld.id} pressure {ld.magnitude:g} MPa is not below the material yield {limit:g} MPa")
                else:
                    out.append(f"rule5: load {ld.id} pressure {ld.magnitude:g} MPa is not below the material ultimate strength {limit:g} MPa")
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
