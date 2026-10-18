"""Guide boundary must apply independently of object type and reconstruction mode."""
import cv2
import numpy as np
import pytest
from reversecad.capture_region import capture_bounds, region_mask, masked_photo
from reversecad.reconstruction import _mask


@pytest.mark.parametrize('shape',[(100,160),(320,480),(1080,1920)])
def test_normalized_guide_preserves_calibrated_image_coordinates(shape):
    region=[.25,.2,.5,.6]
    mask=region_mask(region,shape)
    ys,xs=np.nonzero(mask)
    assert xs.min()>=shape[1]*.25 and xs.max()<shape[1]*.75
    assert ys.min()>=shape[0]*.2 and ys.max()<shape[0]*.8
    image=np.full((*shape,3),123,np.uint8)
    output=masked_photo(image,region)
    assert output.shape==image.shape
    assert np.all(output[mask]==123) and not output[~mask].any()
    assert np.all(image==123)


@pytest.mark.parametrize('region',[[0,0,0,1],[-.1,0,.5,.5],[0,0,2,1],[0,0,float('nan'),1]])
def test_invalid_guide_never_falls_back_to_full_scene(region):
    with pytest.raises(ValueError):capture_bounds(region,(100,100))


def test_depth_mask_and_user_include_cannot_escape_guide(tmp_path):
    np.ones((100,160),np.uint8).tofile(tmp_path/'mask.u8')
    f={'frame_id':'0','mask_path':'mask.u8','capture_region':[.5,.2,.4,.5]}
    annotation={'mask_corrections':{'0':{'include_polygons':[[[0,0],[159,0],[159,99],[0,99]]]}}}
    selected,source=_mask(tmp_path,f,np.full((100,160),.3),annotation)
    assert np.array_equal(selected,region_mask(f['capture_region'],selected.shape))
    assert 'capture_guide' in source


def test_depth_seed_uses_offcenter_guide_not_full_image_center(tmp_path):
    depth=np.full((100,160),.8)
    depth[25:75,110:150]=.3
    f={'frame_id':'0','capture_region':[.65,.2,.3,.6]}
    selected,_=_mask(tmp_path,f,depth,{})
    assert selected[50,130] and not selected[50,80]
    assert not selected[~region_mask(f['capture_region'],depth.shape)].any()


def test_actual_colmap_features_stay_inside_guide(tmp_path):
    import pycolmap as pc
    from reversecad.photo_alignment import write_alignment_image
    rng=np.random.default_rng(19)
    image=cv2.GaussianBlur(rng.integers(0,256,(480,640,3),dtype=np.uint8),(3,3),0)
    cv2.imwrite(str(tmp_path/'source.jpg'),image)
    images=tmp_path/'images';images.mkdir();masks=tmp_path/'masks';masks.mkdir()
    f={'frame_id':'0','rgb_path':'source.jpg','capture_region':[.25,.2,.5,.6]}
    write_alignment_image(tmp_path,f,images,masks)
    db=tmp_path/'features.db'
    pc.extract_features(db,images,camera_mode=pc.CameraMode.SINGLE,
        reader_options={'camera_model':'PINHOLE','camera_params':'600,600,320,240','mask_path':str(masks)},
        extraction_options={'num_threads':2,'max_image_size':640},device=pc.Device.cpu)
    import sqlite3
    with sqlite3.connect(db) as connection:
        rows,cols,data=connection.execute('select rows,cols,data from keypoints').fetchone()
    keypoints=np.frombuffer(data,dtype=np.float32).reshape(rows,cols)
    assert len(keypoints)>10
    assert np.all(keypoints[:,:2]>=[160,96]) and np.all(keypoints[:,:2]<[480,384])
