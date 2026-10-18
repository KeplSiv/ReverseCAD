#!/usr/bin/env python3
"""Synthetic byte/geometry integration input, never a phone or accuracy result."""
import argparse
import json
import struct
import hashlib
from pathlib import Path
import numpy as np
from generate_fixtures import generate_package

p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args()
if a.output.exists():p.error('Output must be new')
# Independent analytic ray renderer owns scene geometry; reconstruction never sees its oracle.
truth=generate_package(a.output,degradation='rgb_textured')
# Evaluation oracle is deliberately outside the immutable capture package.
a.output.with_name(a.output.name+'-truth.json').write_text(json.dumps(truth,indent=2))
root=a.output;(root/'sparse').mkdir()
frames=[json.loads(x) for x in (root/'frames.jsonl').read_text().splitlines()]
stream=bytearray();events=[]
fields=[('points','f',4),('confidences','f',1),('cameraPixels','d',2),('undistortedCameraPixels','d',2),
        ('euclideanDistances','f',1),('intensities','f',1),('signalToNoiseRatios','f',1),('bankIds','B',1),('spotIds','B',1),('echoIds','B',1),('flags','I',1)]
for i,f in enumerate(frames):
    f['sensor_observation']={'source_timestamp_s':f['timestamp_s'],'arrival_timestamp_s':f['timestamp_s']+.01,
       'clock':'host_monotonic_seconds','physical_camera':{'verified':True,'device_type':'AVCaptureDeviceTypeBuiltInWideAngleCamera','device_id':'synthetic-wide','position':'back'},'evidence_kind':'synthetic_simulation_not_a_device'}
    f['capture_region']=[0,0,1,1]
    depth=np.fromfile(root/f['depth_path'],dtype='<f4').reshape(f['depth_height'],f['depth_width'])
    valid=np.argwhere(depth>.05)
    # 28 addresses per packet, three echo slots. Selected native rays lie on the rendered object.
    sample=valid[np.linspace(0,len(valid)-1,28,dtype=int)]
    K=np.asarray(f['intrinsics']).reshape(3,3,order='F').copy()
    ratios=np.array([f['depth_width']/f['rgb_width'],f['depth_height']/f['rgb_height']])
    K[0,0]*=ratios[0];K[1,1]*=ratios[1];K[:2,2]=(K[:2,2]+.5)*ratios-.5
    values={n:[] for n,fmt,width in fields}
    for j,(y,x) in enumerate(sample):
      z=float(depth[y,x]);xyz=np.array([(x-K[0,2])*z/K[0,0],(y-K[1,2])*z/K[1,1],z])*1000
      for e in range(3):
        q=xyz if e==0 else np.zeros(3)
        row={'points':[*q,0.],'confidences':1. if e==0 else 0.,'cameraPixels':[x,y],'undistortedCameraPixels':[x,y],
             'euclideanDistances':float(np.linalg.norm(q)),'intensities':1.,'signalToNoiseRatios':20.,'bankIds':(i%4)*2+j//14,'spotIds':j%14,'echoIds':e,'flags':0}
        for n in values:values[n].append(row[n])
    offset=128;offsets=[];chunks=[]
    for name,fmt,width in fields:
      chunk=b''.join(struct.pack('<'+fmt*width,*(v if width>1 else [v])) for v in values[name]);offsets.append(offset);chunks.append(chunk);offset+=len(chunk)
    data=struct.pack('<16Q',2,84,*offsets,0,offset,0)+b''.join(chunks)
    events.append({'event':'pointCloudSampleBuffer','sequence':i+1,'pts':f['timestamp_s'],'host':f['timestamp_s']+.01,
      'seriesOffset':len(stream),'seriesBytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
      'sensorMetadata':{'PortType':'PortTypeBackSparseTimeOfFlight','source':'synthetic_fixture'}});stream.extend(data)
(root/'sparse/origin-packets.bin').write_bytes(stream)
(root/'sparse/origin-events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in events))
(root/'sparse/calibration.json').write_text(json.dumps({'schema_version':1,'T_sparse_camera':np.eye(4).flatten(order='F').tolist(),
 'direction':'camera_cv_to_sparse','translation_unit':'mm','layout':'column_major','camera_type':'AVCaptureDeviceTypeBuiltInWideAngleCamera','source':'synthetic_fixture'}))
(root/'frames.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in frames))
m=json.loads((root/'manifest.json').read_text());m['sparse_capture']={'schema_version':1,'mode':'sparse_range_rgb','status':'available',
'packet_path':'sparse/origin-packets.bin','event_path':'sparse/origin-events.jsonl','calibration_path':'sparse/calibration.json'}
(root/'manifest.json').write_text(json.dumps(m,indent=2))
(root/'checksums.json').write_text(json.dumps({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name!='checksums.json'},indent=2))
print('Synthetic fixture:',root)
