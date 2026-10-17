"""Short-lived geometry worker. JSON in/out; AR world meters remain unchanged."""
import json,sys,time
from pathlib import Path
import numpy as np


def predict_live(body):
    from .contracts import LiveGeometryRequest
    from .geometry_prediction import predict_geometry
    import open3d as o3d
    request=LiveGeometryRequest.model_validate(body)
    v=np.asarray(request.vertices); f=np.asarray(request.triangles); cameras=np.asarray(request.camera_positions)
    center=(v.min(0)+v.max(0))/2; rays=cameras-center
    lengths=np.linalg.norm(rays,axis=1)
    directions=rays/np.maximum(lengths[:,None],1e-9)
    angle=float(np.degrees(np.arccos(np.clip((directions@directions.T).min(),-1,1))))
    result={'session_id':request.session_id,'sequence':request.sequence,'unit':'mm','status':'need_views',
            'candidates':[],'message':'Move slowly to another side of the object.', 'damage_confirmed':False,
            'physical_fit':'not_tested','view_span_degrees':angle}
    if angle<8:return result
    mesh=o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(v),o3d.utility.Vector3iVector(f))
    mesh.remove_duplicated_vertices();mesh.remove_duplicated_triangles();mesh.remove_degenerate_triangles();mesh.remove_unreferenced_vertices()
    # Meshes used for the live ghost are coarse; no fine-detail claim is made.
    candidates,report=predict_geometry(mesh,fast=True,max_candidates=3)
    for i,c in enumerate(candidates):
        patch=c['patch']
        result['candidates'].append({'id':str(i),'method':c['pattern_kind'],
            'mesh':{'vertices':(patch['vertices']*1000).tolist(),'triangles':patch['faces'].tolist(),'unit':'mm'},
            'support_score':c['support_score'],'assumptions':c['assumptions']})
    result.update(status='provisional' if candidates else 'need_views',seconds=report['seconds'],
        message='Possible missing geometry — provisional, inspect from another angle.' if candidates else 'No supported pattern yet. Show an intact feature and the opening from another side.')
    return result


if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(16,18))
    start=time.monotonic()
    result=predict_live(json.loads(Path(sys.argv[1]).read_text()))
    result['worker_seconds']=time.monotonic()-start
    Path(sys.argv[2]).write_text(json.dumps(result,allow_nan=False))
