import json
import numpy as np
import pytest
from reversecad.reference_donor import load_reference_set, build_reference_solid


def test_library_is_explicitly_scoped_to_same_object(tmp_path):
    scan=tmp_path/'scan';scan.mkdir()
    library=tmp_path/'library.json'
    library.write_text(json.dumps({'schema_version':1,'status':'estimated_prototype','scan_ids':['same-object']}))
    (scan/'manifest.json').write_text(json.dumps({'scan_id':'different-object'}))
    assert load_reference_set(scan,library) is None
    (scan/'manifest.json').write_text(json.dumps({'scan_id':'same-object'}))
    assert load_reference_set(scan,library)['status']=='estimated_prototype'


def test_edge_reference_cannot_build_corner():
    with pytest.raises(ValueError,match='type'):
        build_reference_solid(np.array([[-5,-5],[5,-5],[5,5],[-5,5]]),10,(0,0),{'piece_type':'edge'})


@pytest.mark.parametrize('kind,cell',[('edge',(1,0)),('corner',(0,0))])
def test_estimated_connectors_are_closed_and_preserve_scale(kind,cell):
    theta=np.linspace(0,2*np.pi,16,endpoint=False)
    spec={'piece_type':kind,'images':['synthetic-reference.jpg'],'ratio_source':'synthetic test proportions',
          'foot_outline':np.column_stack([np.cos(theta),np.sin(theta)]).tolist(),
          'ratios':dict(body_rounding=.06,stem_width=.22,stem_thickness=.22,stem_length=.3,
                        foot_width=.7,foot_thickness=.6,shoulder_length=.25,rim_height=.04,tip_length=.08)}
    boundary=np.array([[-5,-5],[5,-5],[5,5],[-5,5]])
    small,shape,evidence=build_reference_solid(boundary,10,cell,spec)
    large,_,_=build_reference_solid(boundary*2,20,cell,spec)
    assert small.is_volume and small.body_count==1 and shape.isValid()
    assert np.isclose(large.volume/small.volume,8,rtol=.005)
    assert small.bounds[0,2]<-10  # Connector extends behind the outer body.
    assert evidence['method']=='image_guided_parametric_approximation'


@pytest.mark.parametrize('kind,cell',[('corner',(0,0)),('edge',(1,0))])
@pytest.mark.parametrize('version',[2,5])
def test_visible_relief_is_real_void_with_material_remaining(kind,cell,version):
    import cadquery as cq
    theta=np.linspace(0,2*np.pi,20,endpoint=False)
    spec={'piece_type':kind,'images':['synthetic.jpg'],'ratio_source':'synthetic',
          'foot_outline':np.column_stack([np.cos(theta),np.sin(theta)]).tolist(),
          'ratios':dict(body_rounding=.06,stem_width=.27,stem_thickness=.26,stem_length=.4,
                        foot_width=1.1,foot_thickness=1.,shoulder_length=.33,rim_height=.05,tip_length=.08),
          'details':dict(version=2,body_scoop_radius=.34,body_scoop_offset=.54,
                         stem_channel_radius=.047,foot_recess_depth=.045,foot_groove_depth=.085,
                         observations=[{'evidence':'Synthetic test geometry'}])}
    boundary=np.array([[-10,-10],[10,-10],[10,10],[-10,10]])
    mesh,solid,evidence=build_reference_solid(boundary,20,cell,spec)
    assert mesh.is_volume and mesh.body_count==1
    assert solid.isValid() and len(solid.Solids())==1
    assert solid.isInside(cq.Vector(0,0,-.5))  # Outer face remains material.
    records=evidence['detail_operations']
    for op in records:
        if 'void_probe_mm' in op:
            assert not solid.isInside(cq.Vector(*op['void_probe_mm']))
    n=np.r_[-(np.array(cell,float)-1),-1.];n/=np.linalg.norm(n)
    # Probe the modeled foot center and its floor independently of rendering.
    root=np.array([0.,0.,-10.])+n*(.38 if kind=='corner' else .22)*20
    tip=root+n*((.4-.04)+.33+.05*2.5+.14)*20
    assert solid.isInside(cq.Vector(*(tip-n*.12*20)))
    if kind=='corner':
        assert not solid.isInside(cq.Vector(*(tip-n*.02*20)))
        assert any(x['feature']=='triangular_perimeter_channel' for x in records)
    else:
        assert solid.isInside(cq.Vector(*(tip+n*.05*20)))
        assert any(x['feature']=='rounded_edge_retaining_tab' for x in records)


def test_preview_keeps_sharp_cad_normals_without_changing_export():
    import cadquery as cq
    from reversecad.reference_donor import cad_surface_preview
    solid=cq.Workplane('XY').box(10,10,10).val()
    vertices,faces,normals=cad_surface_preview(solid)
    # Each of a cube's eight positions needs three independent face normals;
    # averaging them was making flat CAD faces look dented in SceneKit.
    assert len(np.unique(vertices,axis=0))==8
    assert len(vertices)==24
    assert np.allclose(np.linalg.norm(normals,axis=1),1)
    for face in faces:
        assert np.allclose(normals[face],normals[face[0]])
    assert solid.Volume()==pytest.approx(1000)


def test_assembly_rejects_intersecting_closed_pieces():
    import cadquery as cq
    from reversecad.reference_donor import validate_reference_assembly
    a=cq.Workplane('XY').box(10,10,10).val()
    with pytest.raises(ValueError,match='intersect'):
        validate_reference_assembly([a,a.translate((9,0,0))])
    result=validate_reference_assembly([a,a.translate((10.1,0,0))])
    assert result['status']=='no_solid_intersections'
    assert result['pairs'][0]['intersection_volume_mm3']==pytest.approx(0)
    assert result['physical_fit']=='not_tested'


def test_curved_preview_normals_follow_the_cad_surface():
    import cadquery as cq
    from reversecad.reference_donor import cad_surface_preview
    solid=cq.Workplane('XY').sphere(10).val()
    vertices,faces,normals=cad_surface_preview(solid)
    assert np.allclose(normals,vertices/10,atol=1e-6)


def test_failed_assembly_does_not_publish_partial_exports(tmp_path,monkeypatch):
    import reversecad.face_first as module
    def reject(face,profiles,cells,directory,references):
        (directory/'replacement_01.step').write_text('rejected geometry')
        raise ValueError('Reference connectors intersect')
    monkeypatch.setattr(module,'_make_pieces',reject)
    with pytest.raises(ValueError,match='intersect'):
        module.make_pieces({},[],[],tmp_path)
    assert list(tmp_path.iterdir())==[]
