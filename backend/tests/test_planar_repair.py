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
