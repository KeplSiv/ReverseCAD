"""Offline geometry prototype: PYTHONPATH=backend python scripts/propose_pattern_repair.py mesh.ply output_dir"""
import argparse,json
from pathlib import Path
import open3d as o3d
import trimesh
from reversecad.pattern_completion import propose_patterns
p=argparse.ArgumentParser();p.add_argument('mesh',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
loaded=trimesh.load(str(a.mesh),force='mesh')
mesh=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(loaded.vertices),o3d.utility.Vector3iVector(loaded.faces))
candidates,report=propose_patterns(mesh)
a.output.mkdir(parents=True,exist_ok=True)
report['proposals']=[]
for index,c in enumerate(candidates):
 patch=c.pop('patch');t=c.pop('transform')
 out=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(patch['vertices']),o3d.utility.Vector3iVector(patch['faces']))
 out.compute_vertex_normals();name=f'proposal_{index}.ply';o3d.io.write_triangle_mesh(str(a.output/name),out)
 report['proposals'].append({**c,'mesh':name,'transform':t.tolist(), 'source_triangles':patch['source_triangle_indices'].tolist()})
(a.output/'pattern_report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='proposals'},indent=2))
