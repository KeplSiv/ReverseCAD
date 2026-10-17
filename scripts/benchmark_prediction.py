#!/usr/bin/env python3
"""Predict first, then score against removed ground truth. Reports failures too."""
import argparse,json,time
from pathlib import Path
import numpy as np
import open3d as o3d
from reversecad.geometry_prediction import predict_geometry,evaluate_patch
from reversecad.prediction_cases import make_case
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--quick',action='store_true');p.add_argument('--noise-fraction',type=float,default=0);a=p.parse_args()
if not 0<=a.noise_fraction<=.01:p.error('noise fraction must be between 0 and 0.01')
a.output.mkdir(parents=True,exist_ok=True);results=[]
for kind in ['rail','radial','bracket','planar','asymmetric']:
    for broken in ([False] if kind=='asymmetric' else [True,False]):
        for orientation,scale in ([(0,.007)] if a.quick else [(0,.007),(1,.003)]):
            observed,truth=make_case(kind,broken,orientation,scale)
            if a.noise_fraction:
                amplitude=np.linalg.norm(observed.extents)*a.noise_fraction
                observed.vertices += np.random.default_rng(27).uniform(-amplitude,amplitude,observed.vertices.shape)
            native=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(observed.vertices),o3d.utility.Vector3iVector(observed.faces))
            candidates,report=predict_geometry(native)
            scores=[]
            for c in candidates:
                score=evaluate_patch(c['patch'],truth,observed) if broken and truth is not None else {}
                scores.append({'method':c['pattern_kind'],'support_score':c['support_score'],**score})
            item={'case':kind,'noise_fraction':a.noise_fraction,'broken':broken,'orientation':orientation,'scale':scale,'candidates':scores,'seconds':report['seconds'],
                  'top1_pass':scores[0]['symmetric_p95_fraction_of_extent']<.015 if broken and scores else (not scores if not broken else False),
                  'any_pass':any(s['symmetric_p95_fraction_of_extent']<.015 for s in scores) if broken else not scores}
            results.append(item);print(json.dumps(item),flush=True)
            if broken:
                for stale in a.output.glob(f'{kind}-{orientation}-proposal-*.ply'):stale.unlink()
                observed.export(a.output/f'{kind}-{orientation}-observed.ply');truth.export(a.output/f'{kind}-{orientation}-truth.ply')
                for i,c in enumerate(candidates):
                    import trimesh
                    trimesh.Trimesh(c['patch']['vertices'],c['patch']['faces'],process=False).export(a.output/f'{kind}-{orientation}-proposal-{i+1}.ply')
            (a.output/'benchmark.json').write_text(json.dumps({'schema_version':1,'cases':results,'units':'arbitrary metric scale','threshold':'Symmetric p95 surface error < 1.5% of observed extent; negatives require abstention',
                'scope':'Synthetic clean meshes; not phone accuracy or manufacturing tolerance','top1_passed':sum(x['top1_pass'] for x in results),'case_count':len(results)},indent=2))
