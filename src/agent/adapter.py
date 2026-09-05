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
