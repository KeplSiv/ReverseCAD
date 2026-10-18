"""Calibrated rendered scenes exercise detection through placement and export.

These establish the algorithm's contract, not real-camera or physical-fit
accuracy. The scene generator does not call the reconstruction's shape fitter.
"""
import cv2
import numpy as np
import pytest
from reversecad.face_first import repair_from_faces
from reversecad.geometry import project


@pytest.mark.parametrize('missing',[
    {(0,0)}, {(0,0),(0,1)}, {(0,0),(2,2)}, {(0,0),(2,0),(1,2)}])
def test_calibrated_views_recover_corner_and_multiple_independent_pieces(tmp_path,missing):
    k=np.array([[1500.,0,320],[0,1500.,320],[0,0,1]])
    texture=np.full((600,600),30,np.uint8)
    for r in range(3):
        for c in range(3):
            if (c,r) in missing:continue
            x,y=c*200+12,r*200+12
            cv2.rectangle(texture,(x+30,y),(x+146,y+176),170,-1)
            cv2.rectangle(texture,(x,y+30),(x+176,y+146),170,-1)
            for sx in [30,146]:
                for sy in [30,146]:cv2.circle(texture,(x+sx,y+sy),30,170,-1)
            for i in range(5):cv2.circle(texture,(x+45+i*21,y+70+i%2*25),3,125,-1)
    frames=[]
    for i,x in enumerate([-.009,0,.009]):
        pose=np.eye(4);pose[:3,3]=[x,.002*i,-.30]
        quad,_=project(np.array([[-.03,-.03,0],[.03,-.03,0],[.03,.03,0],[-.03,.03,0]]),k,pose)
        h=cv2.getPerspectiveTransform(np.float32([[0,0],[600,0],[600,600],[0,600]]),quad.astype('float32'))
        image=cv2.warpPerspective(texture,h,(640,640),borderValue=30)
        name=f'{i}.png';cv2.imwrite(str(tmp_path/name),image)
        frames.append({'frame_id':str(i),'rgb_path':name,'image_size':np.array([640,640]),
                       'image_k':k,'pose':pose,'orientation':'up'})
    report=repair_from_faces(frames,tmp_path,tmp_path/'out')
    detected={(c['column'],c['row']) for c in report['target_cells']}
    assert detected==missing
    assert report['width_mm']==pytest.approx(60,abs=1.5)
    assert report['closure']['connected_solids']==len(missing)
    assert report['closure']['watertight']
    assert not report['color_used']
    for piece in report['pieces']:
        assert piece['source_cell']['type']==piece['target_cell']['type']
        assert min(piece['donor_profile']['corner_radii_fraction'])>.10
