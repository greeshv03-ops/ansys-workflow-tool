from dataclasses import dataclass, field
from pathlib import Path
import cadquery as cq

from src.models import Body, FaceLabel, GeometryFeatures

try:
    from OCP.BRep import BRep_Tool
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    _OCP_AVAILABLE = True
except ImportError:
    _OCP_AVAILABLE = False

try:
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDataStd import TDataStd_Name
    _STEP_CAF_AVAILABLE = True
except ImportError:
    _STEP_CAF_AVAILABLE = False


@dataclass
class NamedSolid:
    """Runtime pairing of a Body record with its underlying cadquery Shape.

    Kept out of src.models because it carries a live OCC handle and is only
    used by the viewer, never serialized into SimulationConfig.
    """
    body: Body
    shape: "cq.Shape" = field(repr=False)

_MAX_LABELED_FACES = 100
_MAX_DETAILED_BODIES = 3


class _BBox:
    __slots__ = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")

    def __init__(self, xmin, ymin, zmin, xmax, ymax, zmax):
        self.xmin = xmin
        self.ymin = ymin
        self.zmin = zmin
        self.xmax = xmax
        self.ymax = ymax
        self.zmax = zmax


class GeometryAnalyzer:

    @staticmethod
    def analyze(path: str) -> GeometryFeatures:
        return GeometryAnalyzer.analyze_with_solids(path)[0]

    @staticmethod
    def analyze_with_solids(path: str) -> "tuple[GeometryFeatures, list[NamedSolid]]":
        """Same as analyze() but also returns the live NamedSolids for viewer use.

        Use this from UI code that needs to render the geometry; both outputs
        come from a single STEP/IGES parse.
        """
        ext = Path(path).suffix.lower()
        if ext not in ('.step', '.stp', '.iges', '.igs'):
            raise ValueError(f"Unsupported format '{ext}'. Use STEP or IGES.")

        wp = cq.importers.importStep(path) if ext in ('.step', '.stp') \
            else GeometryAnalyzer._load_iges(path)

        shape = wp.val()
        body_count = len(wp.solids().vals())
        is_assembly = body_count > _MAX_DETAILED_BODIES
        named_solids = GeometryAnalyzer.load_named_solids(path, with_volume=not is_assembly)
        bodies = [ns.body for ns in named_solids]
        body_count = len(named_solids) or body_count

        if is_assembly:
            bb = GeometryAnalyzer._fast_bbox(shape)
            bbox = (
                round(bb.xmax - bb.xmin, 3),
                round(bb.ymax - bb.ymin, 3),
                round(bb.zmax - bb.zmin, 3),
            )
            features = GeometryFeatures(
                bbox=bbox,
                volume=0.0,
                surface_area=0.0,
                body_count=body_count,
                thin_walls=False,
                holes=[],
                symmetry_planes=[],
                sharp_edges=False,
                faces=[],
                bodies=bodies,
            )
            return features, named_solids

        bb = shape.BoundingBox()
        bbox = (
            round(bb.xmax - bb.xmin, 3),
            round(bb.ymax - bb.ymin, 3),
            round(bb.zmax - bb.zmin, 3),
        )
        volume = shape.Volume()
        area = shape.Area()
        features = GeometryFeatures(
            bbox=bbox,
            volume=round(volume, 3),
            surface_area=round(area, 3),
            body_count=body_count,
            thin_walls=GeometryAnalyzer._detect_thin_walls(bbox, volume, area),
            holes=GeometryAnalyzer._detect_holes(wp),
            symmetry_planes=GeometryAnalyzer._detect_symmetry(shape, bbox),
            sharp_edges=GeometryAnalyzer._detect_sharp_edges(wp),
            faces=GeometryAnalyzer._label_faces(wp, bb, bbox),
            bodies=bodies,
        )
        return features, named_solids

    @staticmethod
    def load_named_solids(path: str, with_volume: bool = True) -> list[NamedSolid]:
        """Load each solid in `path` paired with its part name from the file.

        STEP files are read via STEPCAFControl_Reader to recover assembly part
        names; for IGES or anything else, names fall back to "Body 1..N".

        Pass with_volume=False to skip per-solid Volume() integration, which
        is O(N) slow on multi-body assemblies.
        """
        ext = Path(path).suffix.lower()
        if ext in ('.step', '.stp') and _STEP_CAF_AVAILABLE:
            return GeometryAnalyzer._load_named_solids_step(path, with_volume)
        wp = cq.importers.importStep(path) if ext in ('.step', '.stp') \
            else GeometryAnalyzer._load_iges(path)
        return [
            _make_named_solid(i, f"Body {i + 1}", solid, with_volume)
            for i, solid in enumerate(wp.solids().vals())
        ]

    @staticmethod
    def _load_named_solids_step(path: str, with_volume: bool) -> list[NamedSolid]:
        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        reader.ReadFile(path)
        reader.Transfer(doc)

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        free_labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_labels)

        named: list[NamedSolid] = []
        counter = [0]
        for i in range(1, free_labels.Length() + 1):
            _walk_assembly(shape_tool, free_labels.Value(i), named, counter, with_volume)

        if not named:
            wp = cq.importers.importStep(path)
            named = [
                _make_named_solid(i, f"Body {i + 1}", solid, with_volume)
                for i, solid in enumerate(wp.solids().vals())
            ]
        return named

    @staticmethod
    def _fast_bbox(shape):
        """Analytical bounding box (skip triangulation).

        Avoids cadquery's mesh-based BoundingBox() which can take 100+ seconds
        on multi-body assemblies; returns an object with xmin..zmax attributes
        matching shape.BoundingBox()'s interface.
        """
        box = Bnd_Box()
        BRepBndLib.Add_s(shape.wrapped, box, False)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        return _BBox(xmin, ymin, zmin, xmax, ymax, zmax)

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


def _make_named_solid(body_id: int, name: str, solid, with_volume: bool = True) -> NamedSolid:
    if _OCP_AVAILABLE:
        box = Bnd_Box()
        BRepBndLib.Add_s(solid.wrapped, box, False)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    else:
        bb = solid.BoundingBox()
        xmin, ymin, zmin = bb.xmin, bb.ymin, bb.zmin
        xmax, ymax, zmax = bb.xmax, bb.ymax, bb.zmax
    bbox_center = (
        round((xmin + xmax) / 2, 3),
        round((ymin + ymax) / 2, 3),
        round((zmin + zmax) / 2, 3),
    )
    return NamedSolid(
        body=Body(
            id=body_id,
            name=name,
            volume=round(solid.Volume(), 3) if with_volume else 0.0,
            centroid=bbox_center,
            bbox=(
                round(xmax - xmin, 3),
                round(ymax - ymin, 3),
                round(zmax - zmin, 3),
            ),
        ),
        shape=solid,
    )


def _label_name(label) -> str:
    name_attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
        return str(name_attr.Get().ToExtString())
    return ""


def _walk_assembly(shape_tool, label, named, counter, with_volume) -> None:
    """Recursively walk a STEP assembly label tree, appending one NamedSolid per leaf solid.

    Each component (instance) gets the name of the part it references, so all
    instances of "Hex Bolt M8" share a name and the material UI can group them.
    """
    if shape_tool.IsAssembly_s(label):
        components = TDF_LabelSequence()
        shape_tool.GetComponents_s(label, components)
        for i in range(1, components.Length() + 1):
            comp_label = components.Value(i)
            try:
                from OCP.TDF import TDF_Label
                ref_label = TDF_Label()
                if shape_tool.IsReference_s(comp_label) and shape_tool.GetReferredShape_s(comp_label, ref_label):
                    _walk_assembly(shape_tool, ref_label, named, counter, with_volume)
                    continue
            except Exception:
                pass
            _walk_assembly(shape_tool, comp_label, named, counter, with_volume)
        return

    name = _label_name(label) or f"Body {counter[0] + 1}"
    try:
        shape = shape_tool.GetShape_s(label)
        for solid in cq.Workplane().newObject([cq.Shape(shape)]).solids().vals():
            named.append(_make_named_solid(counter[0], name, solid, with_volume))
            counter[0] += 1
    except Exception:
        pass


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
