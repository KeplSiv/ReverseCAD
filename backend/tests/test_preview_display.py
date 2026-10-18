import numpy as np
import pytest
from reversecad.preview_display import orient_preview, display_rotation, piece_color

@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_original_and_overlay_rotate_identically_without_touching_calibration(rotation):
    im=np.arange(18,dtype=np.uint8).reshape(2,3,3)
    frame={'display_rotation_cw_deg':rotation,'intrinsics':[10,0,1,0,10,1,0,0,1],'orientation':'up'}
    before=repr(frame)
    expected=np.rot90(im,-rotation//90)
    assert np.array_equal(orient_preview(im,frame),expected)
    assert np.array_equal(orient_preview(im+30,frame),expected+30)
    assert repr(frame)==before

def test_legacy_portrait_uses_gravity_but_overhead_view_is_not_guessed():
    pose=np.eye(4);pose[:3,:3]=[[0,1,0],[-1,0,0],[0,0,1]]
    raw={'T_world_camera':pose.flatten(order='F').tolist()}
    assert display_rotation(raw)==90
    raw['display_rotation_cw_deg']=0
    assert display_rotation(raw)==0
    assert display_rotation({})==0

def test_piece_palette_is_distinct_and_valid():
    colors=[piece_color(i) for i in range(8)]
    assert len(set(map(tuple,colors)))==8
    assert np.isfinite(colors).all() and np.min(colors)>=0 and np.max(colors)<=1
