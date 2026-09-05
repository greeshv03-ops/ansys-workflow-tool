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

    groups = _group_holes(labels)
    grouped_ids = {fid for g in groups for fid in g.face_ids}

    total_area = features.surface_area or sum(l.area for l in labels)
    keep: list[FaceLabel] = []
    for lbl in labels:
        fid = f"f{lbl.index}"
        if total_area > 0 and lbl.area < PRUNE_FRACTION * total_area and fid not in grouped_ids:
            continue
        keep.append(lbl)

    if len(keep) > FACE_CAP:
        raise ValueError(f"Part has {len(keep)} labeled faces, above the cap of {FACE_CAP}")

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
