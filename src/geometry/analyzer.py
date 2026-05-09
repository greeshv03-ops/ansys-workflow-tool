from pathlib import Path
import cadquery as cq
from src.models import GeometryFeatures


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
        holes = []
        seen_keys = set()
        for face in wp.faces().vals():
            if face.geomType() != "CYLINDER":
                continue
            try:
                from OCP.OCP.BRep import BRep_Tool
                from OCP.OCP.GeomAdaptor import GeomAdaptor_Surface
                from OCP.OCP.GeomAbs import GeomAbs_Cylinder
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
        planes = []
        try:
            from OCP.GProp import GProp_GProps
            from OCP.BRepGProp import BRepGProp
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape.wrapped, props)
            com = props.CentreOfMass()
            bb = shape.BoundingBox()
            bbox_cx = (bb.xmax + bb.xmin) / 2
            bbox_cy = (bb.ymax + bb.ymin) / 2
            bbox_cz = (bb.zmax + bb.zmin) / 2
            tol = min(bbox) * 0.1
            # If COM ≈ bbox center the shape is centrosymmetric; suggest the plane
            # perpendicular to its shortest dimension as the likely symmetry plane.
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
