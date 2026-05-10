from pathlib import Path
import cadquery as cq

from src.models import FaceLabel, GeometryFeatures

try:
    from OCP.BRep import BRep_Tool
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    _OCP_AVAILABLE = True
except ImportError:
    _OCP_AVAILABLE = False

_MAX_LABELED_FACES = 100


class GeometryAnalyzer:

    @staticmethod
    def analyze(path: str) -> GeometryFeatures:
        ext = Path(path).suffix.lower()
        if ext not in ('.step', '.stp', '.iges', '.igs'):
            raise ValueError(f"Unsupported format '{ext}'. Use STEP or IGES.")

        wp = cq.importers.importStep(path) if ext in ('.step', '.stp') \
            else GeometryAnalyzer._load_iges(path)

        shape = wp.val()
        bb = shape.BoundingBox()
        bbox = (
            round(bb.xmax - bb.xmin, 3),
            round(bb.ymax - bb.ymin, 3),
            round(bb.zmax - bb.zmin, 3),
        )
        return GeometryFeatures(
            bbox=bbox,
            volume=round(shape.Volume(), 3),
            surface_area=round(shape.Area(), 3),
            body_count=len(wp.solids().vals()),
            thin_walls=GeometryAnalyzer._detect_thin_walls(bbox, shape.Volume(), shape.Area()),
            holes=GeometryAnalyzer._detect_holes(wp),
            symmetry_planes=GeometryAnalyzer._detect_symmetry(shape, bbox),
            sharp_edges=GeometryAnalyzer._detect_sharp_edges(wp),
            faces=GeometryAnalyzer._label_faces(wp, bb, bbox),
        )

    @staticmethod
    def _load_iges(path: str):
        try:
            from OCP.IGESControl import IGESControl_Reader
        except ImportError:
            raise ValueError("IGES support unavailable in this environment. Convert your file to STEP format.")
        try:
            reader = IGESControl_Reader()
            reader.ReadFile(path)
            reader.TransferRoots()
            return cq.Workplane().newObject([cq.Shape(reader.Shape())])
        except Exception as e:
            raise ValueError(f"Failed to read IGES file: {e}. Re-export from your CAD tool and try again.")

    @staticmethod
    def _detect_thin_walls(bbox, volume, surface_area) -> bool:
        if surface_area == 0:
            return False
        avg_thickness = volume / (surface_area / 2)
        return avg_thickness < min(bbox) / 20

    @staticmethod
    def _detect_holes(wp: cq.Workplane) -> list[dict]:
        if not _OCP_AVAILABLE:
            return []
        holes: list[dict] = []
        seen_keys: set = set()
        for face in wp.faces().vals():
            if face.geomType() != "CYLINDER":
                continue
            try:
                adaptor = GeomAdaptor_Surface(BRep_Tool.Surface_s(face.wrapped))
                if adaptor.GetType() != GeomAbs_Cylinder:
                    continue
                radius = adaptor.Cylinder().Radius()
                ax = adaptor.Cylinder().Axis().Location()
                key = (round(radius, 1), round(ax.X()), round(ax.Y()))
                if key not in seen_keys:
                    seen_keys.add(key)
                    holes.append({
                        "diameter": round(radius * 2, 3),
                        "position": (round(ax.X(), 2), round(ax.Y(), 2), round(ax.Z(), 2)),
                    })
            except Exception:
                pass
        return holes

    @staticmethod
    def _detect_symmetry(shape, bbox: tuple) -> list[str]:
        if not _OCP_AVAILABLE:
            return []
        planes: list[str] = []
        try:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape.wrapped, props)
            com = props.CentreOfMass()
            bb = shape.BoundingBox()
            bbox_cx = (bb.xmax + bb.xmin) / 2
            bbox_cy = (bb.ymax + bb.ymin) / 2
            bbox_cz = (bb.zmax + bb.zmin) / 2
            tol = min(bbox) * 0.1
            if (abs(com.X() - bbox_cx) < tol and
                    abs(com.Y() - bbox_cy) < tol and
                    abs(com.Z() - bbox_cz) < tol):
                dims = {"YZ": bbox[0], "XZ": bbox[1], "XY": bbox[2]}
                planes.append(min(dims, key=dims.get))
        except Exception:
            pass
        return planes

    @staticmethod
    def _detect_sharp_edges(wp: cq.Workplane) -> bool:
        for edge in wp.edges().vals():
            try:
                if edge.geomType() in ("CIRCLE", "ELLIPSE") and edge.Length() < 12.57:
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _label_faces(wp: cq.Workplane, bb, bbox: tuple) -> list[FaceLabel]:
        bbox_min = (bb.xmin, bb.ymin, bb.zmin)
        bbox_max = (bb.xmax, bb.ymax, bb.zmax)
        tol = max(bbox) * 0.01 if max(bbox) > 0 else 0.1
        per_dir_count: dict[str, int] = {}
        plane_other_n = 0
        cyl_n = 0
        cone_n = 0
        sphere_n = 0
        other_n = 0
        labels: list[FaceLabel] = []

        for face in wp.faces().vals():
            try:
                gt = face.geomType()
                area = round(face.Area(), 2)
                c = face.Center()
                centroid = (round(c.x, 2), round(c.y, 2), round(c.z, 2))

                if gt == "PLANE":
                    n = face.normalAt()
                    normal = (round(n.x, 3), round(n.y, 3), round(n.z, 3))
                    direction = _classify_axis_direction(normal)
                    if direction and _at_bbox_extremum(centroid, normal, bbox_min, bbox_max, tol):
                        per_dir_count[direction] = per_dir_count.get(direction, 0) + 1
                        idx = per_dir_count[direction]
                        suffix = f" #{idx}" if idx > 1 else ""
                        name = f"{direction} face{suffix} ({_position_word(direction)}, {area:.0f} mm²)"
                    else:
                        plane_other_n += 1
                        name = f"Planar face #{plane_other_n} (n=({normal[0]},{normal[1]},{normal[2]}), {area:.0f} mm²)"
                    labels.append(FaceLabel(
                        name=name, face_type="planar", area=area,
                        centroid=centroid, normal=normal,
                    ))
                elif gt == "CYLINDER" and _OCP_AVAILABLE:
                    radius = None
                    try:
                        adaptor = GeomAdaptor_Surface(BRep_Tool.Surface_s(face.wrapped))
                        radius = round(adaptor.Cylinder().Radius(), 3)
                    except Exception:
                        pass
                    cyl_n += 1
                    diam_str = f"Ø{radius * 2:.1f} mm" if radius else "Ø?"
                    role = _cylinder_role(radius, bbox)
                    name = f"Cyl{role} #{cyl_n} ({diam_str} @ ({centroid[0]},{centroid[1]},{centroid[2]}))"
                    labels.append(FaceLabel(
                        name=name, face_type="cylindrical", area=area,
                        centroid=centroid, radius=radius,
                    ))
                elif gt == "CONE":
                    cone_n += 1
                    name = f"Conical face #{cone_n} ({area:.0f} mm²)"
                    labels.append(FaceLabel(
                        name=name, face_type="conical", area=area, centroid=centroid,
                    ))
                elif gt == "SPHERE":
                    sphere_n += 1
                    name = f"Spherical face #{sphere_n} ({area:.0f} mm²)"
                    labels.append(FaceLabel(
                        name=name, face_type="spherical", area=area, centroid=centroid,
                    ))
                else:
                    other_n += 1
                    name = f"Face #{other_n} ({gt.lower()}, {area:.0f} mm²)"
                    labels.append(FaceLabel(
                        name=name, face_type=gt.lower(), area=area, centroid=centroid,
                    ))
            except Exception:
                continue

        labels.sort(key=lambda lbl: -lbl.area)
        return labels[:_MAX_LABELED_FACES]


def _classify_axis_direction(normal: tuple[float, float, float]) -> str | None:
    nx, ny, nz = normal
    if abs(nx) > 0.95 and abs(ny) < 0.2 and abs(nz) < 0.2:
        return "+X" if nx > 0 else "-X"
    if abs(ny) > 0.95 and abs(nx) < 0.2 and abs(nz) < 0.2:
        return "+Y" if ny > 0 else "-Y"
    if abs(nz) > 0.95 and abs(nx) < 0.2 and abs(ny) < 0.2:
        return "+Z" if nz > 0 else "-Z"
    return None


def _at_bbox_extremum(centroid, normal, bbox_min, bbox_max, tol) -> bool:
    nx, ny, nz = normal
    if abs(nx) > 0.95:
        target = bbox_max[0] if nx > 0 else bbox_min[0]
        return abs(centroid[0] - target) < tol
    if abs(ny) > 0.95:
        target = bbox_max[1] if ny > 0 else bbox_min[1]
        return abs(centroid[1] - target) < tol
    if abs(nz) > 0.95:
        target = bbox_max[2] if nz > 0 else bbox_min[2]
        return abs(centroid[2] - target) < tol
    return False


def _position_word(direction: str) -> str:
    return {
        "+X": "right", "-X": "left",
        "+Y": "front", "-Y": "back",
        "+Z": "top",   "-Z": "bottom",
    }.get(direction, "")


def _cylinder_role(radius, bbox) -> str:
    if radius is None or max(bbox) <= 0:
        return ""
    diam = radius * 2
    smallest = min(bbox)
    if diam < smallest * 0.5:
        return " hole"
    return " shaft"
