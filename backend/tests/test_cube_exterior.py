"""Independent geometry oracles for the explicitly selected cube exterior mode."""
import numpy as np
import pytest
import open3d as o3d
from scipy.spatial.transform import Rotation
from reversecad.cube_exterior import ray_evidence, fit_cube_frame, locate_missing_edge


def test_unknown_occluded_and_duplicate_views_do_not_prove_missing_material():
    k=np.array([[100.,0,20],[0,100.,20],[0,0,1.]])
    p=np.array([[0.,0.,.3]])
    frame={'k':k,'pose':np.eye(4),'depth':np.zeros((40,40)), 'source_frames':['a','b']}
    assert ray_evidence(p,[frame])[0][0]==0
    frame['depth'][:]=.25
    empty,on,occluded=ray_evidence(p,[frame])
    assert empty[0]==0 and on[0]==0 and occluded[0]==1
    frame['depth'][:]=.32
    assert ray_evidence(p,[frame,{**frame,'source_frames':['a','c']}])[0][0]==1
    assert ray_evidence(p,[frame,{**frame,'source_frames':['c','d']}])[0][0]==2


@pytest.mark.parametrize('width', [.045,.075])
@pytest.mark.parametrize('camera_local', [[.2,.2,.2],[-.2,.2,.2]])
def test_frame_estimates_rotated_cube_width_without_preset_dimensions(width,camera_local):
    r=Rotation.from_euler('xyz',[23,41,-17],degrees=True).as_matrix()
    center=np.array([.03,-.01,.04]);uv=np.linspace(-width/2,width/2,65)
    a,b=np.meshgrid(uv,uv);groups=[]
    for axis in range(3):
        p=np.full((a.size,3),width/2);other=[i for i in range(3) if i!=axis]
        p[:,other]=np.column_stack([a.ravel(),b.ravel()]);groups.append(p@r.T+center)
    # The mean position of a camera orbit need not face every observed plane.
    camera=np.array([camera_local])@r.T+center
    fit=fit_cube_frame(np.concatenate(groups),camera)
    assert abs(fit['width']-width)<.001
    np.testing.assert_allclose(fit['center'],center,atol=.001)


def rendered_cube(missing):
    """Ray cast independently constructed solid cubies, without detector sampling."""
    scene=o3d.t.geometry.RaycastingScene()
    for x in range(3):
        for y in range(3):
            for z in range(3):
                if missing and (x,y,z)==(2,2,1):continue
                box=o3d.geometry.TriangleMesh.create_box(.02,.02,.02)
                box.translate(np.array([x,y,z])*.02-.03)
                scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(box))
    frames=[];k=np.array([[160.,0,100],[0,160.,100],[0,0,1.]])
    yy,xx=np.indices((200,200));dirs=np.stack([(xx-100)/160,(yy-100)/160,np.ones_like(xx)],axis=-1)
    for i,camera in enumerate([[.13,.10,.10],[.10,.13,.10],[.12,.12,.08]]):
        camera=np.array(camera);forward=-camera/np.linalg.norm(camera)
        right=np.cross(forward,[0.,0.,1.]);right/=np.linalg.norm(right)
        down=np.cross(forward,right);pose=np.eye(4);pose[:3,:3]=np.column_stack([right,down,forward]);pose[:3,3]=camera
        rays=np.concatenate([np.broadcast_to(camera,dirs.shape),dirs@pose[:3,:3].T],axis=-1).astype(np.float32)
        depth=scene.cast_rays(o3d.core.Tensor(rays))['t_hit'].numpy();depth[~np.isfinite(depth)]=0
        frames.append({'depth':depth,'k':k,'pose':pose,'source_frames':[str(i),'partner'+str(i)]})
    return frames


def test_detects_only_edge_with_observed_recess_on_both_faces():
    geometry={'center':np.zeros(3),'basis':np.eye(3),'width':.06}
    found,_=locate_missing_edge(geometry,rendered_cube(True))
    assert found['target']==[1.,1.,0.]
    diagnostics={}
    with pytest.raises(ValueError,match='No edge'):
        locate_missing_edge(geometry,rendered_cube(False),diagnostics)
    assert len(diagnostics['tested_edges'])==3
    assert max(c['score'] for c in diagnostics['tested_edges'])==0
