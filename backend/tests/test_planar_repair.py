"""Independent outline/solid checks for rectangular boundary restoration."""
import numpy as np
import pytest
from shapely.geometry import Polygon, box
from reversecad.planar_repair import fit_rectangle, mesh_polygon, candidate_contours


@pytest.mark.parametrize('scale',[.5,1.,2.])
def test_two_separate_missing_corners_and_inferred_dimensions(scale):
    intact=box(0,0,120*scale,80*scale)
    cuts=[Polygon(np.array([[0,0],[25,0],[0,20]])*scale),
          Polygon(np.array([[120,80],[100,80],[120,60]])*scale)]
    observed=intact.difference(cuts[0]).difference(cuts[1])
    result=fit_rectangle(np.array(observed.exterior.coords)[:-1])
    assert len(result['patches'])==2
    assert sum(p.area for p in result['patches'])==pytest.approx(sum(c.area for c in cuts),rel=.001)
    assert sorted([result['width'],result['height']])==pytest.approx([80*scale,120*scale])


def test_intact_rectangle_has_no_replacement():
    result=fit_rectangle(np.array([[0,0],[100,0],[100,60],[0,60]]))
    assert not result['patches']


def test_circle_is_not_rectangular_damage():
    a=np.linspace(0,2*np.pi,360,endpoint=False)
    with pytest.raises(ValueError):fit_rectangle(np.column_stack([np.cos(a),np.sin(a)])*50)


def test_concave_patch_is_closed_and_keeps_boundary(tmp_path):
    import trimesh
    poly=Polygon([(0,0),(30,0),(30,10),(15,9),(10,20),(0,20)])
    solid,_=mesh_polygon(poly,3.2)
    assert solid.is_watertight and solid.body_count==1 and solid.volume==pytest.approx(poly.area*3.2,rel=.001)
    path=tmp_path/'patch.stl';solid.export(path)
    restored=trimesh.load_mesh(path)
    assert restored.is_watertight
    np.testing.assert_allclose(restored.extents,[30,20,3.2],atol=.001)


def test_cropped_foreground_is_not_used_as_complete_outline():
    image=np.zeros((400,600,3),np.uint8)
    image[100:350,:300]=255
    assert not list(candidate_contours(image))


def test_two_patches_survive_3mf_as_two_closed_bodies(tmp_path):
    import trimesh
    meshes=[mesh_polygon(Polygon(c),2.5)[0] for c in [
        [(0,0),(25,0),(0,20)],[(120,80),(100,80),(120,60)]]]
    combined=trimesh.util.concatenate(meshes);combined.units='mm'
    path=tmp_path/'two-pieces.3mf';combined.export(path)
    reopened=trimesh.load(path,force='mesh')
    assert reopened.body_count==2 and reopened.is_watertight
    np.testing.assert_allclose(reopened.extents,combined.extents,atol=.001)


def test_guide_ignores_outside_foreground_and_rejects_cut_boundary():
    import cv2
    image=np.zeros((400,600,3),np.uint8)
    # Large distraction outside the user's guide, small complete part inside.
    cv2.rectangle(image,(15,20),(190,380),(255,255,255),-1)
    cv2.rectangle(image,(290,140),(420,260),(255,255,255),-1)
    region=[.4,.2,.4,.6]
    contours=list(candidate_contours(image,region))
    assert contours
    assert all(c[:,0].min()>240 and c[:,0].max()<480 for c in contours)
    # Crossing the guide must not create a false straight 'original edge'.
    image[:]=0;cv2.rectangle(image,(200,140),(420,260),(255,255,255),-1)
    assert not list(candidate_contours(image,region))


def test_limited_world_tracking_can_produce_single_frame_planar_patch(tmp_path):
    import cv2,json
    from reversecad.planar_repair import reconstruct_planar
    image=np.zeros((400,600,3),np.uint8)
    polygon=np.array([[180,100],[420,100],[420,300],[240,300],[240,260],[180,220]])
    cv2.fillPoly(image,[polygon],(240,240,240));cv2.imwrite(str(tmp_path/'photo.jpg'),image)
    np.full((100,150),.6,dtype='<f4').tofile(tmp_path/'depth.f32')
    np.full((100,150),2,dtype='u1').tofile(tmp_path/'confidence.u8')
    (tmp_path/'manifest.json').write_text('{}')
    frame={'frame_id':'0','rgb_path':'photo.jpg','depth_path':'depth.f32',
           'depth_width':150,'depth_height':100,'depth_row_bytes':600,
           'confidence_path':'confidence.u8','intrinsics':[800,0,0,0,800,0,300,200,1],
           'intrinsics_width':600,'intrinsics_height':400,'tracking_state':'limited',
           'capture_region':[.2,.1,.6,.8]}
    output=tmp_path/'output';output.mkdir()
    result=reconstruct_planar(tmp_path,output,{'scan_id':'test','source':'synthetic'},[frame],{})
    assert result['status']=='proposal_needs_review'
    assert result['metrics']['accepted_frames']==1
    report=json.loads((output/'planar_repair.json').read_text())
    assert len(report['polygons_mm'])==1
    assert sorted([report['width_mm'],report['height_mm']])==pytest.approx([150,180],abs=3)
    preview=cv2.imread(str(output/'planar_overlay.jpg'))
    assert preview.shape[:2]==(320,360)


def test_detected_outline_with_inconsistent_depth_reports_depth_failure(tmp_path):
    import cv2
    from reversecad.planar_repair import analyze_frame
    image=np.zeros((400,600,3),np.uint8)
    cv2.fillPoly(image,[np.array([[180,100],[420,100],[420,300],[240,300],[240,260],[180,220]])],(240,240,240))
    cv2.imwrite(str(tmp_path/'photo.jpg'),image)
    # An obvious photographed outline must not be blamed when its depth fails.
    rng=np.random.default_rng(7)
    rng.uniform(.3,.9,(100,150)).astype('<f4').tofile(tmp_path/'depth.f32')
    frame={'frame_id':'0','rgb_path':'photo.jpg','depth_path':'depth.f32',
           'depth_width':150,'depth_height':100,'depth_row_bytes':600,
           'intrinsics':[800,0,0,0,800,0,300,200,1],
           'intrinsics_width':600,'intrinsics_height':400,
           'capture_region':[.2,.1,.6,.8]}
    with pytest.raises(ValueError,match='depth does not establish a reliable flat surface'):
        analyze_frame(tmp_path,frame)
