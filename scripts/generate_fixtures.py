#!/usr/bin/env python3
"""Independent analytic RGB-D ray renderer. Never imports production reconstruction.

Raw packages contain observations only. Primitive dimensions and evaluation targets
are written in a separate evaluator-only directory, never uploaded to the service.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

VERSION = 1
ROOT = Path(__file__).resolve().parents[1]


def box(lo, hi):
    return {"kind": "box", "min_m": list(lo), "max_m": list(hi)}


def scene(name: str, heldout: bool = False):
    """Geometry is in meters, x right/y up/z towards the front view."""
    if name == "calibration_block":
        size = np.array([.083, .047, .031] if heldout else [.100, .060, .040])
        primitives = [box(-size / 2, size / 2)]
    elif name == "broken_bridge":
        span, width = (.097, .137) if heldout else (.080, .120)
        primitives = [box([-.5*width,-.030,-.010], [.5*width,.030,0])]
        # Only two surviving feet/stubs; no replacement grip is rendered.
        for x in [-span/2, span/2]:
            primitives += [box([x-.010,-.010,0],[x+.010,.010,.012])]
        primitives += [box([-span/2-.004,-.006,.012],[-span/2+.004,.006,.021])]
    elif name == "cup":
        radius, height = (.0435, .103) if heldout else (.035, .090)
        primitives = [{"kind":"cup", "radius_m":radius,"inner_radius_m":radius-.003,
                       "bottom_y_m":-height/2,"top_y_m":height/2,"bottom_thickness_m":.004}]
        # Missing handle; two short visible contact stubs on the +x side.
        for y in [-height*.28,height*.28]:
            primitives += [box([radius-.002,y-.006,-.005],[radius+.006,y+.006,.005])]
    elif name == "bracket":
        width, length, height = (.071,.087,.049) if heldout else (.060,.075,.040)
        primitives = [box([-width/2,-.004,-length/2],[width/2,0,length/2]),
                      box([-width/2,0,length/2-.004],[width/2,height,length/2])]
    elif name == "asymmetric":
        size = .013 if heldout else .010
        primitives = [box([-.045,-.025,-.020],[.035,.015,.015]),
                      box([.035,-.012,-.008],[.035+size,.006,.010]),
                      box([-.040,.015,.005],[-.022,.015+2.3*size,.020]),
                      box([-.012,-.023,.015],[.011,-.004,.015+size])]
    else:
        raise ValueError(name)
    low, high = bounds(primitives)
    return primitives, low, high


def bounds(primitives):
    lows, highs = [], []
    for s in primitives:
        if s["kind"] == "box":
            lows.append(s["min_m"]); highs.append(s["max_m"])
        else:
            r=s["radius_m"]
            lows.append([-r,s["bottom_y_m"],-r]);highs.append([r,s["top_y_m"],r])
    return np.min(lows,axis=0),np.max(highs,axis=0)


def intersect_box(origin, directions, s):
    lo,hi=np.asarray(s["min_m"]),np.asarray(s["max_m"])
    with np.errstate(divide="ignore",invalid="ignore"):
        a=(lo-origin)/directions;b=(hi-origin)/directions
    near=np.max(np.minimum(a,b),axis=-1);far=np.min(np.maximum(a,b),axis=-1)
    return np.where((far>=near)&(far>0),np.where(near>0,near,far),np.inf)


def intersect_cup(origin,directions,s):
    """Intersect outer/inner radial surfaces and annular top + bottom disks."""
    candidates=[]
    ylo,yhi=s["bottom_y_m"],s["top_y_m"]
    for radius,ylow in [(s["radius_m"],ylo),(s["inner_radius_m"],ylo+s["bottom_thickness_m"])]:
        a=directions[...,0]**2+directions[...,2]**2
        b=2*(origin[0]*directions[...,0]+origin[2]*directions[...,2])
        c=origin[0]**2+origin[2]**2-radius**2
        disc=b*b-4*a*c
        for sign in [-1,1]:
            with np.errstate(divide="ignore",invalid="ignore"):
                t=(-b+sign*np.sqrt(np.maximum(disc,0)))/(2*a)
            y=origin[1]+t*directions[...,1]
            candidates.append(np.where((disc>=0)&(t>0)&(y>=ylow)&(y<=yhi),t,np.inf))
    for y,rmin,rmax in [(ylo,0,s["radius_m"]),(ylo+s["bottom_thickness_m"],0,s["inner_radius_m"]),(yhi,s["inner_radius_m"],s["radius_m"])]:
        with np.errstate(divide="ignore",invalid="ignore"):
            t=(y-origin[1])/directions[...,1]
        p=origin+t[...,None]*directions
        r=np.sqrt(p[...,0]**2+p[...,2]**2)
        candidates.append(np.where((t>0)&(r>=rmin)&(r<=rmax),t,np.inf))
    return np.min(candidates,axis=0)


def camera_pose(position, target):
    forward=np.asarray(target)-position;forward/=np.linalg.norm(forward)
    right=np.cross(forward,np.array([0.,1.,0.]));right/=np.linalg.norm(right)
    up=np.cross(right,forward)
    pose=np.eye(4);pose[:3,:3]=np.column_stack([right,up,-forward]);pose[:3,3]=position
    return pose


def render(primitives,pose,width,height,fx,fy,cx,cy, low_texture=False, rich_texture=False):
    yy,xx=np.mgrid[:height,:width]
    ray_camera=np.stack([(xx-cx)/fx,-(yy-cy)/fy,-np.ones_like(xx)],axis=-1)
    directions=ray_camera@pose[:3,:3].T
    origin=pose[:3,3]
    ts=np.stack([(intersect_box if p["kind"]=="box" else intersect_cup)(origin,directions,p) for p in primitives])
    depth=ts.min(axis=0);foreground=np.isfinite(depth)
    depth=np.where(foreground,depth,1.0)
    p=origin+depth[...,None]*directions
    # Texture depends on object coordinates, not camera coordinates: valid
    # cross-view features, unlike independent per-image checkerboards.
    base=95+65*np.sin(p*420)+45*np.cos(p[..., [1,2,0]]*270)
    checks=(np.floor((p[...,0]+.1)*650)+np.floor((p[...,1]+.1)*650)+np.floor((p[...,2]+.1)*650))%2
    color=np.clip(base+checks[...,None]*35,20,235).astype(np.uint8)
    if rich_texture:
        grid=np.floor((p+.2)/.0045).astype(np.int64)
        hashed=(grid[...,0]*73856093)^(grid[...,1]*19349663)^(grid[...,2]*83492791)
        color=np.stack([35+((hashed>>shift)&191) for shift in [0,8,16]],axis=-1).astype(np.uint8)
    color[~foreground]=[32,38,45]
    if low_texture:color[foreground]=[150,155,160]
    return depth.astype(np.float32),color,foreground


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_package(destination: Path, name="calibration_block", heldout=False, degradation="clean", seed=211, frame_count=12):
    rng=np.random.default_rng(seed)
    primitives,lo,hi=scene(name,heldout)
    destination.mkdir(parents=True,exist_ok=True)
    for sub in ["rgb","depth","confidence","masks"]:(destination/sub).mkdir(exist_ok=True)
    target=(lo+hi)/2
    width,height=160,120
    rgbw,rgbh=(640,480) if degradation=="rgb_textured" else (320,240)
    if degradation=="rgb_textured":frame_count=24
    fx,fy=220.,218.;cx,cy=78.7,60.2
    resolution_ratio=rgbw/width
    rgbfx,rgbfy=fx*resolution_ratio,fy*resolution_ratio
    rgbcx,rgbcy=(cx+.5)*resolution_ratio-.5,(cy+.5)*resolution_ratio-.5
    frames=[]
    selected_count=2 if degradation=="partial_coverage" else frame_count
    segment_transform=np.eye(4);segment_transform[:3,3]=[.14,-.06,.03]
    segments=[{"segment_id":"segment-0","T_object_world":np.eye(4).flatten(order="F").tolist(),"registered":True}]
    if degradation in ["origin_reset","registered_reset"]:
        segments.append({"segment_id":"segment-1","T_object_world":segment_transform.flatten(order="F").tolist(),"registered":degradation=="registered_reset"})
    for index in range(selected_count):
        angle=2*np.pi*index/frame_count+(0.173 if heldout else 0.071)
        elevation=(.51 if index%2==0 else -.37)+(0.12 if heldout else 0)
        if degradation=="rgb_textured":elevation=.2+.12*math.sin(angle*2)
        radius=.29 if heldout else .31
        position=target+radius*np.array([math.cos(elevation)*math.sin(angle),math.sin(elevation),math.cos(elevation)*math.cos(angle)])
        pose=camera_pose(position,target)
        depth,_,mask=render(primitives,pose,width,height,fx,fy,cx,cy)
        _,rgb,_=render(primitives,pose,rgbw,rgbh,rgbfx,rgbfy,rgbcx,rgbcy,degradation=="low_texture",degradation=="rgb_textured")
        confidence=np.where(mask,2,0).astype(np.uint8)
        if degradation=="noise":
            depth[mask]+=rng.normal(0,.0015,mask.sum()).astype(np.float32)
            outliers=mask&(rng.random(mask.shape)<.05);depth[outliers]+=.025;confidence[outliers]=0
        elif degradation=="depth_bias":depth[mask]*=1.04
        elif degradation=="depth_holes":depth[mask&(rng.random(mask.shape)<.45)]=0
        elif degradation=="invalid_depth":
            selector=rng.random(mask.shape);depth[mask&(selector<.03)]=np.nan;depth[mask&(selector>=.03)&(selector<.06)]=-1;depth[mask&(selector>=.06)&(selector<.09)]=0
        elif degradation=="occlusion":
            cut=(np.indices(mask.shape)[1]>width*.48)&(np.indices(mask.shape)[0]<height*.6)
            depth[cut]=.15;mask[cut]=False;confidence[cut]=0
        elif degradation=="blur":rgb=cv2.GaussianBlur(rgb,(31,31),9)
        elif degradation=="pose_drift":pose[:3,3]+=[index*.0012,0,0]
        if degradation=="mismatched_image_sizes" and index==0:rgb=rgb[:-7,:,:]
        localw,localh,localrgbw,localrgbh=width,height,rgbw,rgbh
        localfx,localfy,localcx,localcy=rgbfx,rgbfy,rgbcx,rgbcy
        if degradation=="portrait_raw":
            # Clockwise raw-pixel rotation with fully transformed calibration and
            # optical axes, not a portrait display matrix applied to old K.
            depth=np.rot90(depth,-1).copy();mask=np.rot90(mask,-1).copy()
            confidence=np.rot90(confidence,-1).copy();rgb=np.rot90(rgb,-1).copy()
            localw,localh=height,width;localrgbw,localrgbh=rgbh,rgbw
            localfx,localfy=rgbfy,rgbfx;localcx,localcy=rgbh-1-rgbcy,rgbcx
            optical=np.eye(4);optical[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]]
            pose=pose@optical
        identifier=f"{index:04d}"
        rgbpath=f"rgb/{identifier}.jpg";depthpath=f"depth/{identifier}.f32";confpath=f"confidence/{identifier}.u8";maskpath=f"masks/{identifier}.u8"
        cv2.imwrite(str(destination/rgbpath),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,95])
        rowbytes=localw*4
        if degradation=="padded_stride":
            padded=np.zeros((height,width+4),dtype="<f4");padded[:,:width]=depth;depthdata=padded.tobytes();rowbytes=(width+4)*4
        else:depthdata=depth.astype("<f4").tobytes()
        (destination/depthpath).write_bytes(depthdata)
        (destination/confpath).write_bytes(confidence.tobytes())
        (destination/maskpath).write_bytes((mask.astype(np.uint8)*255).tobytes())
        segment="segment-0"
        if degradation in ["origin_reset","registered_reset"] and index>=frame_count//2:
            segment="segment-1";pose=np.linalg.inv(segment_transform)@pose
        accepted=degradation!="blur"
        gap=3 if degradation=="timestamp_gap" and index>=frame_count//2 else 0
        frames.append({"schema_version":1,"scan_id":destination.name,"segment_id":segment,"frame_id":identifier,
                       "timestamp_s":round(index*.25+gap,6),"rgb_path":rgbpath,"rgb_width":localrgbw,"rgb_height":localrgbh,"orientation":"up",
                       "depth_path":None if degradation=="missing_depth" else depthpath,"depth_width":localw,"depth_height":localh,
                       "depth_row_bytes":rowbytes,"depth_byte_order":"little",
                       "confidence_path":None if degradation=="missing_confidence" else confpath,
                       "mask_path":None if degradation=="unmasked" else maskpath,
                       "intrinsics":[localfx,0,0,0,localfy,0,localcx,localcy,1],"intrinsics_width":localrgbw,"intrinsics_height":localrgbh,
                       "T_world_camera":pose.flatten(order="F").tolist(),"tracking_state":"normal",
                       "quality":{"blur_score":float(cv2.Laplacian(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),cv2.CV_64F).var()),"accepted":accepted,"reasons":[] if accepted else ["motion_blur"]}})
    manifest={"schema_version":1,"scan_id":destination.name,"source":"synthetic","device":"Independent analytic ray renderer v1 (not a phone)","created_at":"2026-10-16T00:00:00Z","complete":degradation!="incomplete","segments":segments,"frame_count":len(frames)}
    (destination/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    (destination/"frames.jsonl").write_text("".join(json.dumps(f,separators=(",",":"))+"\n" for f in frames))
    files=sorted(p for p in destination.rglob("*") if p.is_file() and p.name!="checksums.json")
    (destination/"checksums.json").write_text(json.dumps({p.relative_to(destination).as_posix():sha(p) for p in files},indent=2)+"\n")
    return {"schema_version":1,"name":destination.name,"scene":name,"heldout_dimensions":heldout,"seed":seed,"degradation":"clean" if degradation=="rgb_textured" else degradation,"render_variant":degradation,"primitives":primitives,
            "bounds_mm":{"min":(lo*1000).tolist(),"max":(hi*1000).tolist(),"extent":((hi-lo)*1000).tolist()},
            "gate":"clean_dimension_error_le_max_0.5mm_1pct" if degradation in ("clean","rgb_textured") else "quality_or_explicit_failure",
            "reference_unit":"m","alignment":"none; object coordinates are already metric","renderer_version":VERSION,
            "package_manifest_sha256":sha(destination/"manifest.json")}


def generate_suite(output:Path, oracle_dir:Path):
    oracle_dir.mkdir(parents=True,exist_ok=True)
    result=[]
    for name in ["calibration_block","broken_bridge","cup","bracket","asymmetric"]:
        for heldout in [False,True]:
            label=name+("_heldout" if heldout else "_clean")
            oracle=generate_package(output/label,name,heldout,seed=227 if heldout else 211)
            (oracle_dir/f"{label}.json").write_text(json.dumps(oracle,indent=2)+"\n");result.append(label)
    for degradation in ["noise","depth_bias","depth_holes","invalid_depth","occlusion","blur","low_texture","pose_drift","origin_reset","registered_reset","missing_depth","missing_confidence","timestamp_gap","mismatched_image_sizes","incomplete","partial_coverage","padded_stride","unmasked","portrait_raw","rgb_textured"]:
        label="calibration_block_"+degradation
        oracle=generate_package(output/label,degradation=degradation)
        (oracle_dir/f"{label}.json").write_text(json.dumps(oracle,indent=2)+"\n");result.append(label)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=ROOT/"fixtures"/"generated")
    p.add_argument("--oracles",type=Path,default=ROOT/"fixtures"/"oracles")
    p.add_argument("--sample-only",action="store_true")
    a=p.parse_args()
    if a.sample_only:
        oracle=generate_package(a.output,"broken_bridge")
        a.oracles.mkdir(parents=True,exist_ok=True)
        (a.oracles/f"{a.output.name}.json").write_text(json.dumps(oracle,indent=2)+"\n")
        print(json.dumps({"sample":str(a.output),"frames":12,"ground_truth_directory":str(a.oracles)}))
    else:
        names=generate_suite(a.output,a.oracles)
        print(json.dumps({"fixture_count":len(names),"input_directory":str(a.output),"ground_truth_directory":str(a.oracles)}))


if __name__=="__main__":main()
