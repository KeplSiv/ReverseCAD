"""Cube demo: infer a genuinely missing repeated cell, not a preselected location."""
import base64
import io
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reversecad.cube import analyze_cube_face, build_outer_cubie
from reversecad.service import create_app


def photographed_face(missing):
    canvas = np.full((750, 850, 3), (57, 49, 44), dtype=np.uint8)
    square = np.full((600, 600, 3), (32, 31, 29), dtype=np.uint8)
    for row in range(3):
        for col in range(3):
            if (row, col) == missing:
                cv2.rectangle(square, (col * 200 + 35, row * 200 + 35),
                              (col * 200 + 165, row * 200 + 165), (78, 71, 64), -1)
            else:
                cv2.rectangle(square, (col * 200 + 13, row * 200 + 13),
                              (col * 200 + 187, row * 200 + 187), (222, 230, 239), -1)
    corners = np.float32([[135, 210], [655, 95], [720, 615], [205, 670]])
    transform = cv2.getPerspectiveTransform(np.float32([[0, 0], [600, 0], [600, 600], [0, 600]]), corners)
    warped = cv2.warpPerspective(square, transform, (850, 750))
    mask = cv2.warpPerspective(np.full((600, 600), 255, dtype=np.uint8), transform, (850, 750))
    canvas[mask > 0] = warped[mask > 0]
    stream = io.BytesIO()
    Image.fromarray(canvas).save(stream, format="JPEG", quality=70)
    return stream.getvalue(), (corners / [850, 750]).tolist()


@pytest.mark.parametrize("missing", [(0, 1), (1, 0), (1, 2), (2, 1)])
def test_detects_missing_edge_from_color_outlier(missing):
    photo, corners = photographed_face(missing)
    result = analyze_cube_face(photo, corners)
    assert result["missing_cell"] == {"row": missing[0], "column": missing[1], "type": "edge"}
    assert result["confidence"] == "high"
    assert len(result["missing_polygon"]) == 4
    assert result["measurement_status"] == "needs_independent_ruler_or_calipers"


def test_outer_cubie_exports_editable_source_and_valid_step():
    artifacts = build_outer_cubie(57, .6, 1.2)
    files = {item["name"]: base64.b64decode(item["base64"]) for item in artifacts}
    assert {"outer_cubie.py", "outer_cubie.step", "outer_cubie.stl", "measurements.json", "repair_plan.json"} == set(files)
    assert b"ISO-10303-21" in files["outer_cubie.step"]
    assert json.loads(files["measurements.json"])["outer_side_mm"] == pytest.approx(18.4)
    assert json.loads(files["measurements.json"])["hidden_connector"] == "not_modeled"


def test_cube_routes_require_pairing_and_report_scope(tmp_path):
    token = "cube-demo-pairing-token-12345"
    app = create_app(data_dir=tmp_path, pairing_token=token, workers_enabled=False)
    photo, corners = photographed_face((1, 0))
    with TestClient(app) as client:
        body = {"photo_base64": base64.b64encode(photo).decode(), "corners": corners}
        assert client.post("/v1/cube/analyze", json=body).status_code == 401
        auth = {"Authorization": f"Bearer {token}"}
        response = client.post("/v1/cube/analyze", json=body, headers=auth)
        assert response.status_code == 200
        assert response.json()["missing_cell"]["type"] == "edge"
        response = client.post("/v1/cube/exterior", json={"face_width_mm":57,"piece_gap_mm":.6,"corner_radius_mm":1.2}, headers=auth)
        assert response.status_code == 200
        assert response.json()["scope"] == "exterior_envelope_only"
        assert response.json()["physical_fit"] == "not_tested"

@pytest.mark.parametrize("missing", [(0, 1), (1, 0), (1, 2), (2, 1)])
def test_automatic_corners_find_missing_cell(missing):
    photo, expected = photographed_face(missing)
    result = analyze_cube_face(photo)
    assert result["missing_cell"]["row"] == missing[0]
    assert result["missing_cell"]["column"] == missing[1]
    assert result["detection_method"] == "automatic_color_hull_grid"
    assert np.max(np.linalg.norm(np.asarray(result["face_corners"]) - expected, axis=1)) < .08

@pytest.mark.parametrize("missing", [None, (0, 0)])
def test_automatic_rejects_blank_or_complete_face(missing):
    from reversecad.cube import CubeInputError
    if missing is None:
        image = Image.new('RGB', (600, 600), 'white')
        stream = io.BytesIO(); image.save(stream, format='JPEG'); photo = stream.getvalue()
    else:
        photo, _ = photographed_face((-1, -1))
    with pytest.raises(CubeInputError):
        analyze_cube_face(photo)


def test_automatic_api_accepts_photo_without_corners(tmp_path):
    app = create_app(data_dir=tmp_path, pairing_token='automatic-cube-test-token', workers_enabled=False)
    photo, _ = photographed_face((1, 2))
    with TestClient(app) as client:
        response = client.post('/v1/cube/analyze', json={'photo_base64': base64.b64encode(photo).decode()},
                               headers={'Authorization': 'Bearer automatic-cube-test-token'})
        assert response.status_code == 200
        assert response.json()['missing_cell']['column'] == 2


def test_repair_program_replays_and_validates_each_solid():
    from reversecad.cad_program import cube_program, execute_cube_program
    program = cube_program(18.4, 1.2)
    shape, checks = execute_cube_program(program)
    assert [c['operation'] for c in checks] == ['profile', 'body', 'rounding']
    assert all(c['valid'] for c in checks)
    assert checks[-1]['volume_mm3'] < checks[-2]['volume_mm3']
    assert shape.val().BoundingBox().xlen == pytest.approx(18.4, abs=.001)
    program['parameters']['side_mm'] = 20
    edited, _ = execute_cube_program(program)
    assert edited.val().BoundingBox().xlen == pytest.approx(20, abs=.001)
    program['operations'][1]['op'] = 'run_python'
    with pytest.raises(ValueError, match='Unsupported'):
        execute_cube_program(program)


def test_export_preserves_detection_and_program_provenance():
    photo, _ = photographed_face((1, 0))
    analysis = analyze_cube_face(photo)
    artifacts = build_outer_cubie(54, .6, 1.2, analysis)
    plan = json.loads(base64.b64decode(next(a for a in artifacts if a['name'] == 'repair_plan.json')['base64']))
    assert plan['evidence']['photo_sha256'] == analysis['photo_sha256']
    assert plan['evidence']['missing_cell'] == {'row': 1, 'column': 0}
    assert plan['parameters']['side_mm'] == pytest.approx(17.4)
    assert all(c['valid'] for c in plan['validation'])
    analysis['confidence'] = 'needs_review'
    with pytest.raises(ValueError, match='Review'):
        build_outer_cubie(54, .6, 1.2, analysis)


def test_photo_outline_spacing_scales_with_measured_width(tmp_path):
    photo, _ = photographed_face((1, 0))
    analysis = analyze_cube_face(photo)
    details = analysis['exterior_details']
    assert details['gap_source'] == 'estimated_visible_outline_spacing'
    assert 0 < details['gap_face_fraction'] < .06
    assert details['radius_source'] == 'rounded_cubie_prior_not_measured'
    app = create_app(data_dir=tmp_path, pairing_token='auto-detail-dimensions-token', workers_enabled=False)
    with TestClient(app) as client:
        response = client.post('/v1/cube/exterior', json={'face_width_mm': 54, 'analysis': analysis},
                               headers={'Authorization':'Bearer auto-detail-dimensions-token'})
        assert response.status_code == 200
        files = {a['name']: base64.b64decode(a['base64']) for a in response.json()['artifacts']}
        measured = json.loads(files['measurements.json'])
        assert measured['piece_gap_mm'] == pytest.approx(54 * details['gap_face_fraction'])
