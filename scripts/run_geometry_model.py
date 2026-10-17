"""Isolated MapAnything adapter. Install its official package in a separate env.

Inputs/outputs are local numeric arrays; this never imports the CAD service or
executes generated code. The Apache checkpoint must already be cached.
"""
import argparse,json,time,gc
from pathlib import Path
import numpy as np
import cv2
from PIL import Image
import torch
from mapanything.models import MapAnything
from mapanything.utils.image import preprocess_inputs
from mapanything.utils.device import to_device

p=argparse.ArgumentParser();p.add_argument('request',type=Path);p.add_argument('output',type=Path);p.add_argument('--modes',nargs='+',choices=['rgb','depth'],default=['rgb','depth']);a=p.parse_args()
request=json.loads(a.request.read_text());a.output.mkdir(parents=True,exist_ok=True)
packet=np.load(request['arrays'],allow_pickle=False)
device='mps' if torch.backends.mps.is_available() else 'cpu'
if device=='mps':torch.mps.set_per_process_memory_fraction(.55)
torch.set_num_threads(2)
started=time.monotonic()
model=MapAnything.from_pretrained('facebook/map-anything-apache',local_files_only=True).eval().to(device)
load_seconds=time.monotonic()-started
for mode in a.modes:
    start=time.monotonic()
    try:
        views=[]
        for i,path in enumerate(request['images']):
            image=Image.open(path).convert('RGB')
            view={'img':image,'intrinsics':torch.tensor(packet['intrinsics'][i],dtype=torch.float32)}
            if mode=='depth':
                native=packet['depth'][i]
                native=np.where(np.isfinite(native)&(native>0),native,0).astype(np.float32)
                view['depth_z']=torch.from_numpy(cv2.resize(native,image.size,interpolation=cv2.INTER_NEAREST))
                view['is_metric_scale']=torch.ones(1,dtype=torch.bool)
            views.append(view)
        processed=preprocess_inputs(views,resize_mode='fixed_mapping',resolution_set=518)
        processed=to_device(processed,device)
        with torch.inference_mode():
            predictions=model.infer(processed,memory_efficient_inference=True,minibatch_size=1,
                use_amp=False,apply_mask=True,mask_edges=True,apply_confidence_mask=True,
                confidence_percentile=20,use_multiview_confidence=False)
        arrays={}
        for i,pred in enumerate(predictions):
            for key in ['pts3d','depth_z','intrinsics','camera_poses','img_no_norm','mask','confidence','non_ambiguous_mask']:
                value=pred.get(key)
                if isinstance(value,torch.Tensor):arrays[f'{i}_{key}']=value.detach().float().cpu().numpy()
        np.savez_compressed(a.output/f'{mode}.npz',**arrays)
        report={'status':'complete','checkpoint':'facebook/map-anything-apache','device':device,
                'source_frames':request['frame_ids'],'seconds':time.monotonic()-start,'load_seconds':load_seconds,
                'inputs':'RGB + intrinsics' if mode=='rgb' else 'RGB + intrinsics + masked native depth',
                'accuracy':'uncalibrated','missing_piece_generated':False}
        (a.output/f'{mode}.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report),flush=True)
        del predictions,processed,views,arrays;gc.collect()
        if device=='mps':torch.mps.empty_cache()
    except Exception as exc:
        (a.output/f'{mode}.json').write_text(json.dumps({'status':'failed','reason':type(exc).__name__+': '+str(exc)[:500],'device':device,'seconds':time.monotonic()-start}))
        print(mode,type(exc).__name__,str(exc)[:500],flush=True)
        gc.collect()
        if device=='mps':torch.mps.empty_cache()
