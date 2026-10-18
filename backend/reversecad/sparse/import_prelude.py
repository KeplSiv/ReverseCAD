"""Read-only conversion of original Prelude fixtures to the versioned extension."""
from __future__ import annotations
import base64
import hashlib
import json
import shutil
from pathlib import Path
import cv2
import numpy as np
from .capture import WIDE,PRIMARY_SHA256,write_json
from .decoder import load_recording


def recorded_plane(source, frame, kind):
    """Read an original plane or its journaled series slice, verifying its hash."""
    metadata = frame['original' if kind == 'depth' else 'confidence']['planes'][0]
    standalone = source / metadata['file']
    if standalone.is_file():
        data = standalone.read_bytes()
    else:
        series = source / ('depth-series.f32' if kind == 'depth' else 'confidence-series.u8')
        offset = frame.get(kind + 'SeriesOffset')
        if offset is None or not series.is_file():
            return None
        with series.open('rb') as stream:
            stream.seek(offset)
            data = stream.read(metadata['bytes'])
    if len(data) != metadata['bytes'] or hashlib.sha256(data).hexdigest() != metadata['sha256']:
        raise ValueError('Original ' + kind + ' plane hash mismatch')
    width_bytes = metadata['width'] * (4 if kind == 'depth' else 1)
    return b''.join(data[y * metadata['bytesPerRow']:y * metadata['bytesPerRow'] + width_bytes]
                    for y in range(metadata['height']))


def import_recording(source,output,region=None):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists() or output==source or source in output.parents:
        raise ValueError('Use a new output directory outside the original recording')
    packets=load_recording(source)
    sha=hashlib.sha256((source/'origin-packets.bin').read_bytes()).hexdigest()
    if source.name.endswith('B3C530') and sha!=PRIMARY_SHA256:raise ValueError('Primary recording SHA-256 differs')
    real=json.loads((source/'real-recording.json').read_text())
    channels=[c for c in real['channels'] if any(p.get('sourceType')==WIDE and p.get('position')==1 for p in c['source']['ports'])]
    if len(channels)!=1:raise ValueError('Unique physical rear 1× source was not identified')
    channel=channels[0];physical=next(p for p in channel['source']['ports'] if p.get('sourceType')==WIDE)
    images=[json.loads(l) for l in (source/'real-camera-frames.jsonl').read_text().splitlines()]
    images=[r for r in images if r.get('event')=='realFrame' and r['channel']==channel['channel'] and r['appended']]
    meta=[json.loads(l) for l in (source/'frames.jsonl').read_text().splitlines()]
    depths=[r for r in meta if r.get('kind')=='depth' and r.get('calibration')]
    events=[json.loads(l) for l in (source/'origin-events.jsonl').read_text().splitlines()]
    raw=next((r.get('extrinsicsMap',{}).get(WIDE) for r in events if r.get('event')=='depthSensorExtrinsics'),None)
    if not raw:raise ValueError('Missing captured wide-camera extrinsic')
    data=base64.b64decode(raw['base64'])
    if hashlib.sha256(data).hexdigest()!=raw['sha256']:raise ValueError('Extrinsic hash mismatch')
    T=np.frombuffer(data,dtype='<f4').astype(float).reshape(4,4,order='F');T[3]=[0,0,0,1]
    output.mkdir(parents=True)
    for d in ['sparse','rgb','video','depth','confidence']:(output/d).mkdir()
    for name in ['origin-packets.bin','origin-events.jsonl','real-camera-frames.jsonl','real-recording.json','frames.jsonl']:
        shutil.copyfile(source/name,output/'sparse'/name)
    shutil.copyfile(source/channel['file'],output/'video'/'source.mov')
    write_json(output/'sparse'/'calibration.json',{'schema_version':1,'T_sparse_camera':T.flatten(order='F'),
          'direction':'camera_cv_to_sparse','translation_unit':'mm','layout':'column_major','camera_type':WIDE,
          'source':'recorded ARDepthSensor._extrinsicsMap','raw_extrinsic':raw,'physical_emitter_origin_verified':False})
    reader=cv2.VideoCapture(str(source/channel['file']));decoded=[]
    while True:
        ok,im=reader.read()
        if not ok:break
        decoded.append(im)
    reader.release()
    if len(decoded)!=len(images):raise ValueError('Movie frame count does not match original appended-frame journal')
    selection=[];last=-float('inf')
    for i,r in enumerate(images):
        if r['pts']-last>=.30:selection.append(i);last=r['pts']
    selection=selection[:48];rows=[]
    scan_id='prelude-'+source.name.split('_')[-1];t0=images[0]['pts']
    for j,i in enumerate(selection):
        image=decoded[i];r=images[i];nearest=min(depths,key=lambda d:abs(d['pts']-r['pts']))
        delta=abs(nearest['pts']-r['pts'])
        if delta>.075:continue
        c=nearest['calibration'];w,h=image.shape[1],image.shape[0]
        if (w,h)!=(c['referenceWidth'],c['referenceHeight']):raise ValueError('Calibration/image resolution mismatch')
        name=f'{j:06d}';image_path=f'rgb/{name}.png';cv2.imwrite(str(output/image_path),image)
        K=np.asarray(c['intrinsics']);pose=np.asarray(c['cameraTransform'])
        row={'schema_version':1,'scan_id':scan_id,'segment_id':'fixture','frame_id':name,'timestamp_s':r['pts']-t0,
             'rgb_path':image_path,'rgb_width':w,'rgb_height':h,'orientation':'up','depth_path':None,
             'depth_width':0,'depth_height':0,'depth_row_bytes':0,'depth_byte_order':'little','confidence_path':None,
             'intrinsics':K.flatten(order='F').tolist(),'intrinsics_width':w,'intrinsics_height':h,
             'T_world_camera':pose.flatten(order='F').tolist(),'tracking_state':'limited',
             'quality':{'accepted':True,'blur_score':float(cv2.Laplacian(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var()),'reasons':['archived_decoder_fixture_not_fresh_object_scan']},
             'capture_region':region or [0,0,1,1],
             'sensor_observation':{'source_timestamp_s':r['pts'],'arrival_timestamp_s':None,
                 'arrival_semantics':'unavailable in original realFrame journal',
                 'clock':'host_monotonic_seconds','physical_camera':{'verified':True,'device_type':WIDE,'device_id':physical['deviceID'],'position':'back'},
                 'source_metadata':r,'calibration_delta_s':delta,'calibration_source':'nearest recorded ARCamera; fixed model, not independently calibrated',
                 'pose_source':'ARKit_black_input_diagnostic_only_not_used','RGB_control':'separate real_image_fork'}}
        # Retain contemporaneous processed depth for a labeled legacy comparison only.
        depth = recorded_plane(source, nearest, 'depth')
        if depth is not None:
            plane=nearest['original'];dw,dh=plane['width'],plane['height']
            row.update(depth_path=f'depth/{name}.f32',depth_width=dw,depth_height=dh,depth_row_bytes=dw*4,depth_calibration_mode='native_arkit')
            (output/row['depth_path']).write_bytes(depth)
            confidence = recorded_plane(source, nearest, 'confidence')
            if confidence is not None:
                row['confidence_path'] = f'confidence/{name}.u8'
                (output/row['confidence_path']).write_bytes(confidence)
            row['sensor_observation']['processed_depth_comparison'] = {
                'timestamp_s': nearest['pts'], 'rgb_delta_s': delta,
                'source': 'separate black-input ARKit processed-depth diagnostic',
                'original_plane_sha256': nearest['original']['planes'][0]['sha256']}
        rows.append(row)
    if not rows:raise ValueError('No usable timed frames')
    (output/'frames.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
    write_json(output/'manifest.json',{'schema_version':1,'scan_id':scan_id,'source':'arkit','device':'recorded Prelude research fixture',
        'created_at':source.name.split('_')[0],'complete':True,'segments':[{'segment_id':'fixture','registered':True,'T_object_world':np.eye(4).flatten(order='F')}],
        'frame_count':len(rows),'sparse_capture':{'schema_version':1,'mode':'sparse_range_rgb','status':'available',
         'packet_path':'sparse/origin-packets.bin','event_path':'sparse/origin-events.jsonl','calibration_path':'sparse/calibration.json'},
        'provenance':{'source_directory':str(source),'original_packet_sha256':sha,'original_video_sha256':hashlib.sha256((source/channel['file']).read_bytes()).hexdigest(),
          'image_transform':'lossy source H264 decoded to original-size PNG; originals retained','acceptance_role':'decoder_registration_fixture_only'}})
    write_json(output/'checksums.json',{p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()})
    return {'scan_id':scan_id,'frames':len(rows),'packets':len(packets),'source_sha256':sha}
