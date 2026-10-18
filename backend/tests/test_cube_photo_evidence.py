"""Independent rendered-image and surface oracles for donor inference."""
import numpy as np
import cv2
import pytest
from reversecad.geometry import project
from reversecad.cube_photo_evidence import locate_photo_edge
from reversecad.cube_counterpart import transfer_edge_points
from reversecad.printable_edge import close_edge
from test_cube_exterior import rendered_cube


def photo_cube(missing=True,one_face=False):
    photos=[];width=.06;pitch=width/3
    for index,camera in enumerate([[.13,.10,.10],[.10,.13,.10],[.12,.12,.08],[.14,.12,.09]]):
        camera=np.array(camera);forward=-camera/np.linalg.norm(camera)
        right=np.cross(forward,[0.,0.,1.]);right/=np.linalg.norm(right)
        down=np.cross(forward,right);pose=np.eye(4);pose[:3,:3]=np.column_stack([right,down,forward]);pose[:3,3]=camera
        k=np.array([[800.,0,320],[0,800.,320],[0,0,1.]])
        image=np.full((640,640,3),45,np.uint8)
        tiles=[]
        for fixed,color in enumerate([(245,125,20),(240,240,240),(40,220,40)]):
            free=[i for i in range(3) if i!=fixed]
            for a in range(-1,2):
                for b in range(-1,2):
                    cell=np.zeros(3,int);cell[fixed]=1;cell[free]=[a,b]
                    local=np.tile(cell*pitch,(4,1));local[:,fixed]=width/2
                    local[:,free]+=np.array([[-.46,-.46],[.46,-.46],[.46,.46],[-.46,.46]])*pitch
                    uv,z=project(local,k,pose)
                    absent=missing and list(cell)==[1,1,0] and (not one_face or fixed==0)
                    tiles.append((float(z.mean()),np.rint(uv).astype(np.int32),(35,35,35) if absent else color))
        for _,quad,color in sorted(tiles,key=lambda x:-x[0]):cv2.fillConvexPoly(image,quad,color)
        photos.append({'frame_id':str(index),'image':image,'image_size':(640,640),'image_k':k,'pose':pose})
    return photos


def test_rgb_repetition_can_nominate_missing_edge_without_gap_depth():
    geometry={'center':np.zeros(3),'basis':np.eye(3),'width':.06}
    missing,_=locate_photo_edge(geometry,photo_cube(),[])
    assert missing['target']==[1,1,0]
    assert missing['gap_depth_required'] is False
    assert missing['requires_visual_confirmation'] is True
    with pytest.raises(ValueError):locate_photo_edge(geometry,photo_cube(False),[])
    with pytest.raises(ValueError):locate_photo_edge(geometry,photo_cube(one_face=True),[])
    with pytest.raises(ValueError):locate_photo_edge(geometry,[photo_cube()[0]]*4,[])
    with pytest.raises(ValueError):locate_photo_edge(geometry,photo_cube(),[
        {'target':[1,1,0],'faces':[{'surface_fraction':.9},{'surface_fraction':.9}]}])


def test_donor_transfer_preserves_ridge_in_observed_coordinates():
    face={'center':np.zeros(3),'basis':np.eye(3),'width':.06}
    u,v=np.meshgrid(np.linspace(-.009,.009,50),np.linspace(-.009,.009,50))
    # Donor at the negative-y edge: two surfaces and a measured top ridge.
    ridge=.0006*np.exp(-(u.ravel()/.0015)**2)
    top=np.column_stack([u.ravel(),v.ravel()-.02,ridge])
    side=np.column_stack([u.ravel(),np.full(u.size,-.03),v.ravel()-.01])
    points=np.vstack([top,side]);missing={'row':1,'column':2}
    donors=transfer_edge_points(points,face,missing)
    assert donors
    transferred,report=donors[0];transform=np.array(report['transform_world_m'])
    np.testing.assert_allclose(transferred,points@transform[:3,:3].T+transform[:3,3],atol=1e-12)
    assert transferred[:,2].max()>.0005


def test_flat_donor_does_not_gain_radial_bulges(tmp_path):
    face={'center':np.array([0.,0.,.03]),'basis':np.eye(3),'width':.06}
    a,b=np.meshgrid(np.linspace(.0101,.0299,50),np.linspace(-.0099,.0099,50))
    top=np.column_stack([a.ravel(),b.ravel(),np.full(a.size,.03)])
    side=np.column_stack([np.full(a.size,.03),b.ravel(),a.ravel()])
    _,report=close_edge(None,face,{'row':1,'column':2},tmp_path,observed_points=np.vstack([top,side]))
    extents=np.ptp(report['bounds_mm'],axis=0)
    np.testing.assert_allclose(extents,[20,20,20],atol=.02)
    assert report['watertight'] and not report['self_intersections']


def test_two_photographed_donor_profiles_export_a_closed_solid(tmp_path):
    from reversecad.cube_photo_evidence import close_photo_donor
    import trimesh
    face={'center':np.array([0.,0.,.03]),'basis':np.eye(3),'width':.06}
    preview,report=close_photo_donor(face,{'row':2,'column':1},{'row':1,'column':2},photo_cube(False),tmp_path)
    assert report['relief_recovered'] is False
    assert all(len(p['frame_ids'])>=3 for p in report['donor_photo_profiles'])
    for name in report['files']:
        mesh=trimesh.load(tmp_path/name,force='mesh',process=True)
        assert mesh.is_watertight and mesh.body_count==1 and mesh.volume>0
        assert np.all(mesh.extents>17) and np.all(mesh.extents<=20.1)
    # The target is the positive-X/positive-Z edge, rather than donor +Y/+Z.
    centroid=np.mean(preview['vertices'],axis=0)
    assert centroid[0]>10 and centroid[2]>10 and abs(centroid[1])<2


def test_photo_frame_recovers_metric_cube_without_three_depth_planes(monkeypatch,tmp_path):
    from reversecad.cube_photo_evidence import frames_from_photo_outlines
    import reversecad.photo_cube as photo
    views=[];corners=np.array([[-.03,-.03,.03],[.03,-.03,.03],[.03,.03,.03],[-.03,.03,.03]])
    for f in photo_cube():
        uv,_=project(corners,f['image_k'],f['pose'])
        views.append((f,{'face_corners':(uv/[640,640]).tolist(),
                         'missing_cell':{'row':1,'column':2,'type':'edge'},'face_color_rgb':[240,240,240]}))
    monkeypatch.setattr(photo,'detect_views',lambda frames,scan:views)
    # No third-face surface samples are needed by calibrated photo triangulation.
    frames=frames_from_photo_outlines([],tmp_path,corners)
    assert len(frames)==4
    for f in frames:
        assert f['evidence']['frame_source']=='calibrated_multiview_face_outline'
        assert f['width']==pytest.approx(.06,abs=1e-5)
        np.testing.assert_allclose(f['center'],0,atol=1e-5)
