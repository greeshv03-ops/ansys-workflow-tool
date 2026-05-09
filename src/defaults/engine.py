from src.models import GeometryFeatures, SimulationType


class SmartDefaultsEngine:

    @staticmethod
    def compute(features: GeometryFeatures, sim_type: SimulationType) -> dict:
        d = {}
        min_dim = min(features.bbox)
        d["element_size_mm"] = round(max(0.5, min(20.0, min_dim / 50)), 2)
        d["element_type"] = "Shell" if features.thin_walls else "Solid"
        d["refinement_zones"] = [
            {"zone_type": "hole", "size_mm": round(h["diameter"] / 8, 3),
             "description": f"Hole dia={h['diameter']}mm at {h['position']}"}
            for h in features.holes
        ]
        if features.sharp_edges:
            d["refinement_zones"].append({
                "zone_type": "edge",
                "size_mm": round(d["element_size_mm"] / 4, 3),
                "description": "Sharp edge stress concentrator",
            })
        d["suggest_symmetry"] = len(features.symmetry_planes) > 0
        d["symmetry_planes"] = features.symmetry_planes
        d["multiple_bodies"] = features.body_count > 1

        if sim_type == SimulationType.STATIC_STRUCTURAL:
            d.update({"substeps": 1, "large_deflection": False,
                       "outputs": ["total_deformation", "von_mises_stress", "safety_factor"]})
        elif sim_type == SimulationType.TRANSIENT_STRUCTURAL:
            d.update({"end_time": 1.0, "initial_step": 0.01, "min_step": 0.001,
                       "max_step": 0.1, "integration_method": "Newmark",
                       "outputs": ["total_deformation", "von_mises_stress", "velocity", "acceleration"]})
        elif sim_type == SimulationType.THERMAL_STRUCTURAL:
            d.update({"coupling": "two_way", "end_time": 1.0, "initial_step": 0.1,
                       "min_step": 0.01, "max_step": 1.0,
                       "outputs": ["total_deformation", "von_mises_stress", "temperature", "heat_flux"]})
        return d
