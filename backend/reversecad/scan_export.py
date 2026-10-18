"""Export only observed geometry. Open surfaces remain open, including in STEP."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from .storage import atomic_json


def export_observed_scan(directory: Path, result: dict) -> dict:
    report = {"schema_version": 1, "status": "needs_input", "scan_id": result.get("scan_id"),
              "unit": "mm", "files": [], "hidden_surfaces": "unknown; no hole filling",
              "capture_source": "intercepted_sparse_and_images" if result.get("sparse_reconstruction") else "Apple_processed_scene_depth_and_images",
              "dimensional_accuracy": "not_independently_validated", "physical_fit": "not_tested",
              "cad_kind": "faceted observed surface, not an inferred solid or parametric feature tree"}
    if result.get("status") not in {"ready", "complete"}:
        report["reason"] = "Reconstruction needs more usable observations; measured export withheld."
        atomic_json(directory / "scan_export.json", report)
        return report
    with np.load(directory / "points_measurement.npz", allow_pickle=False) as data:
        points = data["points_m"] * 1000
        colors = data["colors"] if "colors" in data else None
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError("Invalid observed point cloud")
    import open3d as o3d
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    if colors is not None and colors.shape == points.shape and np.isfinite(colors).all():
        cloud.colors = o3d.utility.Vector3dVector(np.clip(colors, 0, 1))
    if not o3d.io.write_point_cloud(str(directory / "observed_points_mm.ply"), cloud):
        raise ValueError("Point cloud export failed")
    files = ["observed_points_mm.ply", "measurements.json"]
    atomic_json(directory / "measurements.json", {"scan_id": result.get("scan_id"), "unit": "mm", "bounds_mm": result.get("bounds_mm"), "measurements": result.get("measurements", []), "primitives": result.get("primitives", []), "uncertainty_budget": result.get("uncertainty_budget"), "capture_source": report["capture_source"], "dimensional_accuracy": report["dimensional_accuracy"]})
    preview = json.loads((directory / "scan_preview.json").read_text())
    vertices = np.asarray(preview["vertices"], dtype=float)
    triangles = np.asarray(preview["triangles"], dtype=int)
    if len(triangles):
        if preview.get("unit") != "mm" or not np.isfinite(vertices).all() or triangles.ndim != 2 or triangles.shape[1] != 3 or triangles.min() < 0 or triangles.max() >= len(vertices):
            raise ValueError("Invalid observed surface")
        mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices), o3d.utility.Vector3iVector(triangles))
        full_surface = directory / "observed_surface_mm.ply"
        if full_surface.is_file():
            full_mesh = o3d.io.read_triangle_mesh(str(full_surface))
            if len(full_mesh.triangles):
                mesh = full_mesh
        mesh.compute_triangle_normals()
        if not o3d.io.write_triangle_mesh(str(directory / "observed_object.stl"), mesh):
            raise ValueError("Surface export failed")
        files.append("observed_object.stl")
        report.update(surface_faces=len(mesh.triangles), watertight=bool(mesh.is_watertight()))
        cad_mesh = mesh
        if len(mesh.triangles) > 20000:
            cad_mesh = mesh.simplify_quadric_decimation(20000, maximum_error=.0625, boundary_weight=10)
        vertices = np.asarray(cad_mesh.vertices)
        triangles = np.asarray(cad_mesh.triangles)
        # Check sampled deviation both ways, without treating it as physical accuracy.
        def distances(source, target):
            scene = o3d.t.geometry.RaycastingScene()
            scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(target))
            v = np.asarray(source.vertices); t = np.asarray(source.triangles)
            samples = np.vstack((v[np.unique(t)], v[t].mean(axis=1)))
            return scene.compute_distance(o3d.core.Tensor(samples.astype(np.float32))).numpy()
        deviation = 0.0 if cad_mesh is mesh else max(float(distances(cad_mesh, mesh).max()), float(distances(mesh, cad_mesh).max()))
        report["cad_approximation"] = {"triangles": len(triangles), "sampled_bidirectional_max_deviation_mm": deviation,
                                       "check_samples": "vertices and face centroids; not a certified Hausdorff bound",
                                       "measurement_points_unchanged": True}
        if len(triangles) > 30000 or deviation > .5:
            report["reason"] = "The STEP approximation did not meet its size/deviation gate; full STL, point cloud and measurements remain available."
        else:
            from OCP.BRep import BRep_Builder
            from OCP.TopoDS import TopoDS_Compound
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
            from OCP.gp import gp_Pnt
            from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
            from OCP.IFSelect import IFSelect_RetDone
            from OCP.Interface import Interface_Static
            compound = TopoDS_Compound(); builder = BRep_Builder(); builder.MakeCompound(compound)
            count = 0
            for triangle in vertices[triangles]:
                if np.linalg.norm(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])) < 1e-10:
                    continue
                polygon = BRepBuilderAPI_MakePolygon()
                for point in triangle:
                    polygon.Add(gp_Pnt(*map(float, point)))
                polygon.Close()
                face = BRepBuilderAPI_MakeFace(polygon.Wire())
                if not face.IsDone():
                    raise ValueError("Observed CAD face could not be constructed")
                builder.Add(compound, face.Face()); count += 1
            if not count:
                raise ValueError("No nondegenerate observed surface faces")
            writer = STEPControl_Writer()
            Interface_Static.SetCVal_s("write.step.unit", "MM")
            if writer.Transfer(compound, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(directory / "observed_object.step")) != IFSelect_RetDone:
                raise ValueError("Observed STEP export failed")
            files.append("observed_object.step")
            report["cad_faces"] = count
    report.update(status="ready", files=files, point_count=len(points))
    atomic_json(directory / "scan_export.json", report)
    return report
