import numpy as np
import pytest
from reversecad.photo_alignment import robust_scale
from reversecad.photo_cube import fit_square, fit_outline, solid_from_outline
from reversecad.geometry import project


def test_metric_scale_rejects_outliers_and_scales_with_observations():
    samples=np.r_[np.linspace(.019,.021,100),[.0001,.8,8,np.nan]]
    scale,report=robust_scale(samples)
    assert abs(scale-.02)<.0001
    assert report['samples']==100
    assert robust_scale(samples*2)[0]==pytest.approx(scale*2)
    with pytest.raises(ValueError):robust_scale([1,2,3])
    with pytest.raises(ValueError):robust_scale(np.linspace(.01,.08,100))


def square_views(width=.06):
    k=np.array([[800.,0,499.5],[0,800.,399.5],[0,0,1.]])
    corners=np.array([[-.5,-.5,0],[.5,-.5,0],[.5,.5,0],[-.5,.5,0]])*width+[0,0,.3]
    views=[]
    for i,x in enumerate([-.04,-.02,.01,.04]):
        p=np.eye(4);p[0,3]=x
        uv,_=project(corners,k,p)
        views.append(({'frame_id':str(i),'pose':p,'image_k':k,'image_size':(1000,800)},
                      {'face_corners':(uv/[1000,800]).tolist()}))
    return views


def test_multiview_square_recovers_scale_and_predicts_held_out_views():
    geometry,views,evidence=fit_square(square_views())
    assert geometry['width']==pytest.approx(.06,abs=1e-5)
    assert len(views)==4
    assert evidence['median_held_out_error_fraction_of_face']<1e-5
    assert fit_square(square_views(.08))[0]['width']==pytest.approx(.08,abs=1e-5)
    with pytest.raises(ValueError):fit_square(square_views()[:2])


def rounded_outline(width=.90,radius=.10):
    y,x=np.indices((200,200));q=np.stack([abs((x+.5)/200-.5),abs((y+.5)/200-.5)],axis=-1)-(width/2-radius)
    return np.linalg.norm(np.maximum(q,0),axis=-1)+np.minimum(q.max(axis=-1),0)-radius<=0


def test_outline_parameters_are_measured_and_solid_has_no_spurious_ridges():
    mask=rounded_outline()
    parameters=fit_outline(mask)
    assert parameters['width_fraction']==pytest.approx(.9,abs=.01)
    assert parameters['radius_fraction']==pytest.approx(.1,abs=.015)
    a=solid_from_outline(mask,20)
    b=solid_from_outline(mask,30)
    assert a.is_watertight and a.is_winding_consistent and a.body_count==1
    np.testing.assert_allclose(b.extents/a.extents,1.5,atol=1e-5)
    assert np.max(abs(a.extents-18))<.3
    assert b.volume/a.volume==pytest.approx(1.5**3,rel=.001)
    # A different observed corner radius must change the output geometry.
    c=solid_from_outline(rounded_outline(radius=.04),20)
    assert c.volume>a.volume
