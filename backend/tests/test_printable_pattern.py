import numpy as np
import pytest
import trimesh
from reversecad.printable_pattern import (close_planar_boundaries, export_printable_pattern,
                                          PatternClosureUnavailable)


def open_box():
    m = trimesh.creation.box([10, 20, 30])
    m.update_faces(m.face_normals[:, 2] < .9)
    return m


def test_planar_cap_retains_donor_and_correct_volume():
    m = open_box()
    solid, report = close_planar_boundaries(m.vertices, m.faces)
    assert solid.is_watertight and solid.volume == pytest.approx(6000)
    assert report['inferred_cap_triangles'] == 2
    assert report['observed_triangles'] == 10
    # Exact donor geometry, no smoothing or hull replacement.
    assert set(map(tuple, m.vertices)) == set(map(tuple, solid.vertices))


def test_nonplanar_boundary_is_not_flattened():
    m = open_box(); v = m.vertices.copy()
    v[np.argmax(v[:, 0]+v[:, 1]+v[:, 2]), 2] += 2
    with pytest.raises(PatternClosureUnavailable, match='curved'):
        close_planar_boundaries(v, m.faces)


def test_disconnected_parts_are_not_joined_by_invented_material():
    a = open_box(); b = a.copy(); b.apply_translation([50,0,0])
    mesh = trimesh.util.concatenate([a,b])
    with pytest.raises(PatternClosureUnavailable, match='disconnected'):
        close_planar_boundaries(mesh.vertices, mesh.faces)


def test_flat_patch_cannot_be_exported_as_a_solid(tmp_path):
    patch = {'vertices': np.array([[0,0,0],[.01,0,0],[0,.01,0]]), 'faces': [[0,1,2]]}
    with pytest.raises(PatternClosureUnavailable):
        export_printable_pattern(patch, tmp_path, 'flat')
    assert not list(tmp_path.glob('*.stl'))


def test_export_reopens_stl_and_3mf_at_metric_size(tmp_path):
    m = open_box()
    preview, report = export_printable_pattern({'vertices':m.vertices/1000, 'faces':m.faces}, tmp_path, 'part')
    assert report['watertight'] and report['physical_fit'] == 'not_tested'
    assert preview['unit'] == 'mm'
    for name in report['files']:
        reopened = trimesh.load(tmp_path/name, force='mesh', process=True)
        assert reopened.is_watertight and reopened.body_count == 1
        np.testing.assert_allclose(reopened.extents, [10,20,30])
        assert reopened.volume == pytest.approx(6000)


def test_already_closed_non_cubic_donor_keeps_its_detail():
    m = trimesh.creation.icosphere(subdivisions=1, radius=8)
    m.vertices[0] *= 1.1
    solid, report = close_planar_boundaries(m.vertices, m.faces)
    assert report['inferred_cap_triangles'] == 0
    assert solid.volume == pytest.approx(m.volume)


def test_solids_touching_only_at_one_vertex_are_not_a_printable_connection():
    from reversecad.printable_pattern import validate_solid
    a = trimesh.creation.box([10,10,10]); b = a.copy(); b.apply_translation([10,10,10])
    mesh = trimesh.util.concatenate([a,b]); mesh.merge_vertices()
    with pytest.raises(PatternClosureUnavailable, match='non-manifold'):
        validate_solid(mesh)
