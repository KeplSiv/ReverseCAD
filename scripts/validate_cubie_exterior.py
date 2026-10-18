"""Replay an immutable phone capture through the production cubie exterior path."""
import argparse
import json
from pathlib import Path
import numpy as np
import trimesh
from reversecad.reconstruction import reconstruct

parser=argparse.ArgumentParser()
parser.add_argument('capture',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
report=reconstruct(args.capture,args.output,{'repair_scope':'cube_exterior'})
summary={'capture':args.capture.name,'status':report['status'],
         'elapsed_s':report['metrics']['elapsed_s'],'physical_fit':'not_tested'}
if report.get('counterpart',{}).get('watertight_replacement'):
    stl=trimesh.load_mesh(args.output/'printable_edge.stl',process=True)
    mf=trimesh.load(args.output/'printable_edge.3mf',force='mesh')
    assert stl.is_watertight and stl.is_winding_consistent and stl.body_count==1 and stl.volume>0
    assert mf.is_watertight and mf.body_count==1
    np.testing.assert_allclose(stl.extents,mf.extents,atol=.001)
    summary.update(closed_solid=True,volume_mm3=float(stl.volume),extents_mm=stl.extents.tolist())
else:
    summary.update(closed_solid=False,reason=report.get('counterpart',{}).get('reason'))
(args.output/'validation_summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
raise SystemExit(0 if summary['closed_solid'] else 1)
