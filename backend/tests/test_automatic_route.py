"""Routing must preserve guide boundaries and abstain on ambiguous evidence."""
import cv2
import numpy as np
from reversecad.automatic_route import decide_route, select_route


def test_conflicting_or_weak_evidence_needs_choice():
    assert decide_route(0, 0) is None
    assert decide_route(1, 0) is None
    assert decide_route(2, 2) is None
    assert decide_route(1, 3) is None
    assert decide_route(3, 0) == 'cube_exterior'
    assert decide_route(0, 1) == 'rectangular_planar'
    assert decide_route(0, 2) == 'rectangular_planar'


def test_repeated_grid_routes_only_inside_box(tmp_path):
    gray = np.full((480, 960), 35, np.uint8)
    for r in range(3):
        for c in range(3):
            if (c, r) != (0, 1):
                cv2.rectangle(gray, (105+c*90, 105+r*90), (185+c*90, 185+r*90), 170, -1)
    cv2.imwrite(str(tmp_path/'photo.png'), gray)
    frames = [{'frame_id': str(i), 'rgb_path':'photo.png', 'capture_region':[0, 0, .5, 1]} for i in range(2)]
    assert select_route(tmp_path, frames)['scope'] == 'cube_exterior'
    for f in frames: f['capture_region'] = [.5, 0, .5, 1]
    assert select_route(tmp_path, frames)['needs_choice']
    for f in frames: f.pop('capture_region')
    assert select_route(tmp_path, frames)['needs_choice']


def test_torn_planar_part_routes_with_depth(tmp_path):
    image = np.zeros((400, 600, 3), np.uint8)
    polygon = np.array([[180,100],[420,100],[420,300],[240,300],[240,260],[180,220]])
    cv2.fillPoly(image,[polygon],(240,240,240))
    cv2.imwrite(str(tmp_path/'photo.png'),image)
    np.full((100,150),.6,dtype='<f4').tofile(tmp_path/'depth.f32')
    frame = {'rgb_path':'photo.png','depth_path':'depth.f32', 'depth_width':150,'depth_height':100,'depth_row_bytes':600,
             'intrinsics':[800,0,0,0,800,0,300,200,1], 'intrinsics_width':600,'intrinsics_height':400,
             'capture_region':[.2,.1,.6,.8]}
    result = select_route(tmp_path,[{**frame, 'frame_id':str(i)} for i in range(2)])
    assert result['scope'] == 'rectangular_planar'


def test_service_contract_accepts_automatic_and_rejects_unknown_scope():
    import pytest
    from pydantic import ValidationError
    from reversecad.contracts import Annotations
    assert Annotations(repair_scope='automatic').repair_scope == 'automatic'
    with pytest.raises(ValidationError):
        Annotations(repair_scope='arbitrary_classifier')
