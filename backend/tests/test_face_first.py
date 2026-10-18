"""Shape-only repair: intact tiles veto damage; guide and closed export hold."""
import cv2
import numpy as np
import pytest
from reversecad.face_first import lattice_candidates, make_piece


def grid(missing=None, intensities=None):
    image=np.full((480,480),35,np.uint8)
    for r in range(3):
        for c in range(3):
            if (c,r)==missing or isinstance(missing,set) and (c,r) in missing:continue
            value=170 if intensities is None else intensities[r*3+c]
            cv2.rectangle(image,(105+c*90,105+r*90),(185+c*90,185+r*90),int(value),-1)
    return image


def test_intact_grid_never_becomes_a_missing_edge():
    assert lattice_candidates(grid(),None)==[]


@pytest.mark.parametrize('missing',[(0,1),(1,0),(2,1),(1,2),(0,0),(2,0),(0,2),(2,2)])
def test_edge_location_comes_from_repeated_boundaries(missing):
    for tones in [None,[80,240,110,210,90,200,120,230,100]]:
        candidates=lattice_candidates(grid(missing,tones),None)
        assert candidates and all(tuple(c['missing'])==missing for c in candidates)


def test_grid_outside_capture_guide_is_not_a_repair():
    image=np.full((480,960),35,np.uint8)
    image[:,:480]=grid((0,1))
    assert lattice_candidates(image,[.5,0,.5,1])==[]


def test_hue_changes_with_identical_boundaries_do_not_change_photo_result():
    from reversecad.face_first import analyze_photo_geometry
    foreground=grid((0,1))>35
    images=[]
    for bgr in [(200,100,50),(50,100,107)]:
        image=np.full((480,480,3),35,np.uint8)
        image[foreground]=bgr;images.append(image)
    assert np.array_equal(*[cv2.cvtColor(im,cv2.COLOR_BGR2GRAY) for im in images])
    results=[analyze_photo_geometry(cv2.imencode('.png',im)[1].tobytes()) for im in images]
    assert results[0]['missing_cell']==results[1]['missing_cell']=={'row':1,'column':0,'type':'edge'}
    assert results[0]['face_corners']==results[1]['face_corners']
    assert all(r['color_used'] is False for r in results)


@pytest.mark.parametrize('missing',[{(0,0),(0,1)},{(0,0),(2,2)},{(0,1),(2,1)},
                                    {(0,0),(2,0),(1,2)},{(0,0),(2,0),(0,2),(1,2)}])
def test_multiple_locations_preserve_their_distinct_types(missing):
    candidates=lattice_candidates(grid(missing),None)
    assert candidates
    assert set(map(tuple,candidates[0]['missing_cells']))==missing


def test_missing_entire_row_cannot_establish_the_original_extent():
    assert lattice_candidates(grid({(0,0),(1,0),(2,0)}),None)==[]


def test_clear_intact_view_vetoes_occlusion_in_another_view():
    from reversecad.face_first import confirm_missing
    damaged=grid((0,1));intact=grid()
    seed=lattice_candidates(damaged,None)[0]
    annotation={'face_corners':(np.asarray(seed['corners'])/480).tolist()}
    views=[({'frame_id':name},annotation) for name in ['a','b','c']]
    with pytest.raises(ValueError,match='not consistent'):
        confirm_missing(views,{'a':damaged,'b':damaged,'c':intact},seed)


def asymmetric_mask():
    mask=np.zeros((280,280),np.uint8)
    cv2.rectangle(mask,(50,50),(230,230),1,-1)
    # Remove a large quarter-circle deficit at the top-left only.
    yy,xx=np.indices(mask.shape)
    corner=(xx<100)&(yy<100)&((xx-100)**2+(yy-100)**2>50**2)
    mask[corner]=0
    return mask


def test_curvature_is_observed_and_asymmetric_not_a_fixed_fillet():
    from reversecad.face_first import outline_profile
    from shapely.geometry import Point,Polygon
    profile=outline_profile(asymmetric_mask())
    radii=profile['corner_radii_fraction']
    assert radii[2]==pytest.approx(.25,abs=.025)
    assert max(radii[i] for i in [0,1,3])<.035
    polygon=Polygon(profile['outline_fraction'])
    assert not polygon.contains(Point(-.43,-.43))
    assert polygon.contains(Point(.43,.43))
    assert profile['median_boundary_error_fraction']<.01


@pytest.mark.parametrize('targets',[[(0,0),(2,2)],[(0,0),(0,1)],[(0,1),(2,1),(1,2)]])
def test_multiple_pieces_have_separate_closed_exports_and_correct_world_positions(tmp_path,targets):
    import trimesh
    from reversecad.face_first import outline_profile,make_pieces,cell_type
    face={'width':.06,'basis':np.diag([1,1,-1]),'center':np.array([.1,.2,.3])}
    profiles=[]
    for target in targets:
        profile=outline_profile(asymmetric_mask())
        profile['source_cell']={'column':2,'row':0 if cell_type(target)=='corner' else 1}
        profiles.append(profile)
    preview,report=make_pieces(face,profiles,targets,tmp_path)
    assert report['connected_solids']==len(targets)
    assert len(preview['colors'])==len(preview['vertices'])
    assert len(set(map(tuple,preview['colors'])))==len(targets)
    for tri in preview['triangles']:
        assert len({tuple(preview['colors'][i]) for i in tri})==1
    world=trimesh.Trimesh(vertices=preview['vertices'],faces=preview['triangles'])
    assert world.is_volume and world.body_count==len(targets)
    centers=np.array([m.bounds.mean(0)[:2] for m in world.split()])
    for c,r in targets:
        assert np.min(np.linalg.norm(centers-([100,200]+(np.array([c,r])-1)*20),axis=1))<.1
    for name in report['files']:
        mesh=trimesh.load(tmp_path/name,force='mesh')
        assert mesh.is_volume
        assert mesh.body_count==(len(targets) if name.startswith('printable_edge') else 1)


def test_corners_cannot_be_repaired_with_an_edge_donor(tmp_path):
    from reversecad.face_first import outline_profile
    profile=outline_profile(asymmetric_mask());profile['source_cell']={'column':2,'row':1}
    with pytest.raises(ValueError,match='cannot share'):
        make_piece({'width':.06},profile,(0,0),tmp_path)


@pytest.mark.parametrize('normal',[1,-1])
def test_closed_donor_export_preserves_outline_and_places_it_in_target(tmp_path,normal):
    import trimesh
    face={'width':.06,'basis':np.diag([1,1,normal]),'center':np.array([.1,.2,.3])}
    profile={'half_extents_fraction':[.45,.4],'radius_fraction':.08,
             'center_fraction':[0.,0.],'width_fraction':.85,
             'source_cell':{'column':2,'row':1}}
    preview,report=make_piece(face,profile,[0,1],tmp_path)
    expected_area=(18*16-(4-np.pi)*1.6**2)
    assert report['watertight'] and not report['hidden_geometry_reconstructed']
    assert report['volume_mm3']==pytest.approx(expected_area*17,rel=.002)
    placed=np.array(preview['vertices'])
    assert (placed.min(0)+placed.max(0))/2==pytest.approx([80,200,300-normal*8.5])
    world_mesh=trimesh.Trimesh(vertices=placed,faces=preview['triangles'])
    assert world_mesh.is_volume
    for name in ['printable_edge.stl','printable_edge.3mf']:
        mesh=trimesh.load(tmp_path/name,force='mesh')
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.body_count==1
        assert mesh.extents==pytest.approx([18,16,17],abs=.001)


def test_cube_scope_does_not_require_dense_surface(monkeypatch,tmp_path):
    from reversecad import face_first
    from reversecad import photo_alignment
    def aligned(*args):return [{'frame_id':'a'}],{'status':'aligned_photos'}
    def repaired(frames,scan,output,**kwargs):
        return {'width_mm':60,'watertight_replacement':True,'color_used':False}
    monkeypatch.setattr(photo_alignment,'align_photos',aligned)
    monkeypatch.setattr(face_first,'repair_from_faces',repaired)
    report=face_first.reconstruct_faces(tmp_path,tmp_path,[],[],{'metrics':{}})
    assert report['status']=='proposal_needs_review'
    assert report['point_count']==0 and report['counterpart']['watertight_replacement']


def test_native_depth_validation_uses_surviving_tiles_not_the_missing_gap():
    from reversecad.face_first import depth_support
    face={'width':.06,'basis':np.eye(3),'center':np.zeros(3)}
    observed=[(c,r) for r in range(3) for c in range(3) if (c,r)!=(0,0)]
    views=[]
    for i in range(3):
        pose=np.eye(4);pose[2,3]=-.3
        depth=np.full((120,120),.3)
        # The missing cell has no trustworthy depth; it must not gate a donor.
        depth[40:53,40:53]=0
        views.append(({'frame_id':str(i),'pose':pose,'depth':depth,
                       'k':np.array([[200.,0,60],[0,200.,60],[0,0,1]])},{}))
    assert depth_support(face,views,observed)['accepted']
    for f,_ in views:f['depth'][:]=.4
    assert not depth_support(face,views,observed)['accepted']
    assert not depth_support(face,views[:2],observed)['accepted']


def test_ghost_does_not_paint_inferred_depth_over_the_photograph(tmp_path):
    from reversecad.face_first import photo_overlay
    import trimesh
    cv2.imwrite(str(tmp_path/'photo.png'),np.full((480,480,3),50,np.uint8))
    face={'width':.06,'basis':np.eye(3),'center':np.zeros(3)}
    pose=np.eye(4);pose[:3,3]=[-.05,0,.3];pose[:3,:3]=np.diag([1,-1,-1])
    f={'frame_id':'f','rgb_path':'photo.png','pose':pose,
       'image_k':np.array([[1000.,0,240],[0,1000.,240],[0,0,1]])}
    a={'face_corners':[[.25,.25],[.75,.25],[.75,.75],[.25,.75]]}
    results=[]
    for thickness in [.005,.04]:
        part=trimesh.creation.box([.018,.018,thickness]);part.apply_translation([0,0,-thickness/2])
        preview={'vertices':(part.vertices*1000).tolist(),'triangles':part.faces.tolist()}
        out=tmp_path/str(thickness);out.mkdir()
        photo_overlay(tmp_path,[(f,a)],face,[(1,0)],out,preview)
        results.append(cv2.imread(str(out/'cube_overlay.jpg')))
    assert np.array_equal(*results)
    assert np.count_nonzero(results[0][:,:,2]>100)>1000


def test_same_face_identity_requires_shared_views_and_consistent_grid_locations():
    from reversecad.face_first import same_tracked_face
    q=np.array([[.2,.2],[.8,.2],[.8,.8],[.2,.8]])
    views=lambda offset:[({'frame_id':str(i)},{'face_corners':(q+offset).tolist()}) for i in range(3)]
    assert same_tracked_face(views(0),views(.015))
    assert not same_tracked_face(views(0),views(.2))
    assert not same_tracked_face(views(0),views(.015)[:1])
