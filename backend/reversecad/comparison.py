"""Bounded comparison of real pipelines on one immutable capture.

A viewable surface, a closed hypothesis, and a physically validated replacement
are different outcomes. No automatic winner is claimed without ground truth.
"""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False))


def mesh_preview(mesh, path, scale=1000):
    import open3d as o3d
    if len(mesh.triangles)>30000:mesh=mesh.simplify_quadric_decimation(30000)
    mesh.remove_unreferenced_vertices()
    if not len(mesh.vertices):return None
    vertices=np.asarray(mesh.vertices)*scale
    if not np.isfinite(vertices).all():raise ValueError('Non-finite preview geometry')
    write_json(path,{'vertices':vertices.tolist(),'triangles':np.asarray(mesh.triangles).tolist(),
                    'colors':np.asarray(mesh.vertex_colors).tolist(),'normals':[],'unit':'mm'})
    return path.name


def base_variant(identifier,title,method):
    return {'id':identifier,'title':title,'method':method,'status':'needs_more_evidence',
            'message':'No supported output.','scan_preview':None,'part_preview':None,
            'print_files':[],'printable':False,'metrics':{},'physical_fit':'not_tested',
            'scope':'experimental_comparison','seconds':0.0}


def copy_result(folder, output, variant, result):
    """Publish only successful validated artifacts; private temporary files stay private."""
    for source,key in [('scan_preview.json','scan_preview'),('counterpart_preview.json','part_preview')]:
        if (folder/source).is_file():
            name=variant['id']+'_'+source;shutil.copyfile(folder/source,output/name);variant[key]=name
    if result.get('watertight_replacement'):
        from .printable_pattern import validate_solid
        import trimesh
        for source in ['printable_edge.stl','printable_edge.3mf']:
            validate_solid(trimesh.load(folder/source,force='mesh',process=True))
        for source in ['printable_edge.stl','printable_edge.3mf','printable_edge.json','counterpart.json']:
            if not (folder/source).is_file():raise ValueError('Validated output set is incomplete')
        for source in ['printable_edge.stl','printable_edge.3mf','printable_edge.json','counterpart.json']:
            name=variant['id']+'_'+source;shutil.copyfile(folder/source,output/name);variant['print_files'].append(name)
        variant['printable']=True;variant['status']='proposal_needs_review'
    variant['message']=result.get('reason','Surface recovered; missing geometry remains unresolved.')
    variant['metrics']={k:result[k] for k in ['photo_geometry','outline_fit','donor'] if k in result}


def learned_outputs(scan_dir, frames, output_dir, progress):
    python=os.environ.get('REVERSECAD_GEOMETRY_PYTHON')
    if not python or not Path(python).is_file():
        return None,'Learned model environment is not configured on the Mac.'
    selected=[frames[i] for i in np.unique(np.linspace(0,len(frames)-1,min(6,len(frames)),dtype=int))]
    if len(selected)<3:return None,'At least three usable views are required.'
    # Inputs and model outputs remain private to this comparison; only bounded
    # previews/reports enter the phone's verified artifact revision.
    arrays=output_dir/'inputs.npz'
    np.savez_compressed(arrays,intrinsics=np.stack([f['image_k'] for f in selected]),depth=np.stack([f['depth'] for f in selected]))
    import cv2
    from .capture_region import masked_photo
    model_images=[]
    for f in selected:
        path=scan_dir/f['rgb_path']
        image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        if image is None:raise ValueError('Model input photo unavailable')
        path=output_dir/(f['frame_id']+'_guided.png')
        if not cv2.imwrite(str(path),masked_photo(image,f.get('capture_region'))):raise ValueError('Cannot prepare guided model image')
        model_images.append(str(path.resolve()))
    request={'arrays':str(arrays),'images':model_images,
             'frame_ids':[f['frame_id'] for f in selected]}
    write_json(output_dir/'request.json',request)
    adapter=Path(__file__).resolve().parents[2]/'scripts/run_geometry_model.py'
    env=os.environ.copy();env.update(PYTORCH_ENABLE_MPS_FALLBACK='1',HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    if os.environ.get('REVERSECAD_MODEL_CACHE'):
        env['HF_HOME']=os.environ['REVERSECAD_MODEL_CACHE'];env['TORCH_HOME']=str(Path(env['HF_HOME'])/'torch')
    progress('reconstructing',.78,'Comparing learned RGB and RGB + depth geometry')
    with (output_dir/'model.log').open('wb') as log:
        process=subprocess.Popen([python,str(adapter),str(output_dir/'request.json'),str(output_dir)],env=env,stdout=log,stderr=log)
        try:process.wait(timeout=240)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()
            completed=any((output_dir/f'{mode}.npz').exists() for mode in ['rgb','depth'])
            return (selected if completed else None),'Learned comparison reached its 240 second budget.'
    if not any((output_dir/f'{mode}.npz').exists() for mode in ['rgb','depth']):
        return None,'The model did not complete inference. See Mac model diagnostics.'
    return selected,None


def learned_surface(packet, selected, mode, output, variant):
    """Keep learned geometry separate from measurements; mask to the same object."""
    import cv2
    from .geometry import unproject
    from .reconstruction import _tsdf
    data=np.load(packet/f'{mode}.npz',allow_pickle=False)
    frames=[];ratios=[]
    for i,original in enumerate(selected):
        depth=np.asarray(data[f'{i}_depth_z']).squeeze().astype(np.float32)
        h,w=depth.shape
        native=cv2.resize(original['depth'],(w,h),interpolation=cv2.INTER_NEAREST)
        valid=np.isfinite(depth)&(depth>0)&(native>0)
        if valid.sum()>30:ratios.extend((native[valid]/depth[valid])[::max(1,int(valid.sum())//1000)].tolist())
    from .photo_alignment import robust_scale
    scale,scale_report=robust_scale(ratios)
    pose0=data['0_camera_poses'].reshape(4,4).copy();pose0[:3,3]*=scale
    world=selected[0]['pose']@np.linalg.inv(pose0)
    native_errors=[];points=[];colors=[]
    for i,original in enumerate(selected):
        depth=np.asarray(data[f'{i}_depth_z']).squeeze().astype(np.float32)*scale
        h,w=depth.shape
        foreground=cv2.resize((original['depth']>0).astype(np.uint8),(w,h),interpolation=cv2.INTER_NEAREST)>0
        if f'{i}_mask' in data:foreground &= data[f'{i}_mask'].squeeze()>0
        depth=np.where(foreground&np.isfinite(depth)&(depth>0),depth,0).astype(np.float32)
        native=cv2.resize(original['depth'],(w,h),interpolation=cv2.INTER_NEAREST)
        both=(depth>0)&(native>0)
        if both.any():native_errors.extend(abs(depth[both]-native[both])[::max(1,int(both.sum())//1000)].tolist())
        pose=data[f'{i}_camera_poses'].reshape(4,4).copy();pose[:3,3]*=scale;pose=world@pose
        k=data[f'{i}_intrinsics'].reshape(3,3)
        rgb=data[f'{i}_img_no_norm'].squeeze()
        rgb=np.clip(rgb*(255 if rgb.max()<=1.01 else 1),0,255).astype(np.uint8)
        frames.append({'depth':depth,'k':k,'pose':pose,'color':rgb,'frame_id':original['frame_id']})
        xyz,pixels=unproject(depth,k,pose)
        points.append(xyz);colors.append(rgb[pixels[:,1],pixels[:,0]]/255)
    if not points or sum(map(len,points))<100:raise ValueError('Too little foreground geometry from model')
    all_points=np.concatenate(points);extent=np.ptp(all_points,axis=0).max()
    if not .005<extent<1.5:raise ValueError('Learned geometry extent is inconsistent with a small object')
    mesh=_tsdf(frames,float(np.clip(extent/250,.0004,.004)),packet)
    variant['scan_preview']=mesh_preview(mesh,output/(variant['id']+'_scan.json'))
    if variant['scan_preview'] is None:
        xyz=np.concatenate(points);rgb=np.concatenate(colors);ids=np.linspace(0,len(xyz)-1,min(20000,len(xyz)),dtype=int)
        name=variant['id']+'_scan.json';write_json(output/name,{'vertices':(xyz[ids]*1000).tolist(),'triangles':[],'colors':rgb[ids].tolist(),'unit':'mm'});variant['scan_preview']=name
    variant['status']='surface_only';variant['message']='Learned surface, scaled against native depth. No replacement is established.'
    variant['metrics'].update(scale_source='native_depth_ratio',scale_dispersion=scale_report['relative_p10_p90_half_range'],
        native_depth_agreement_mm=float(np.median(native_errors)*1000) if native_errors else None,
        triangles=int(len(mesh.triangles)),source_frames=[f['frame_id'] for f in selected])
    if len(mesh.triangles)>=100:
        from .pattern_completion import export_pattern_hypotheses
        candidate_dir=packet/(mode+'_patterns');candidate_dir.mkdir(exist_ok=True)
        hypotheses=export_pattern_hypotheses(mesh,candidate_dir)
        variant['metrics']['pattern_hypotheses']=len(hypotheses.get('candidates',[]))
        # An unverified learned surface is not a measurement basis for a print.
        # Surface hypotheses are inspectable, but cannot promote this method to printable.
        candidates=hypotheses.get('candidates',[])
        if candidates:
            source=candidate_dir/candidates[0]['preview'];name=variant['id']+'_part.json'
            shutil.copyfile(source,output/name);variant['part_preview']=name
            variant['message']='Learned surface with an unverified symmetry proposal. Inspect the orange region; export is blocked.'


def compare_reconstructions(scan_dir,output_dir,base,annotations=None,progress=None):
    from .reconstruction import _load_package,_prepare
    from .face_first import repair_from_faces
    import open3d as o3d
    start=time.monotonic();scan_dir=Path(scan_dir);output_dir=Path(output_dir)
    progress=progress or (lambda *args:None)
    manifest,raw,segments=_load_package(scan_dir)
    frames,*_=_prepare(scan_dir,raw,segments,annotations or {},'rgb_assisted')
    variants=[]
    current=base_variant('current','Current pipeline','Native RGB-D fusion + existing photo fallback')
    current['status']='needs_more_evidence' if base['status']=='needs_input' else 'surface_only'
    if (output_dir/'scan_preview.json').exists():current['scan_preview']='scan_preview.json'
    current['seconds']=float(base.get('metrics',{}).get('elapsed_s',0))
    current['metrics']={'warnings':base.get('warnings',[]),'accepted_frames':len(frames)}
    current['message']=base.get('counterpart',{}).get('reason','Current reconstructed surface.')
    if base.get('counterpart',{}).get('watertight_replacement'):
        current['part_preview']='counterpart_preview.json';current['printable']=True;current['status']='proposal_needs_review'
        current['print_files']=[n for n in ['printable_edge.stl','printable_edge.3mf','printable_edge.json','counterpart.json'] if (output_dir/n).is_file()]
    variants.append(current)
    geometry_report=base.get('pattern_hypotheses',{})
    geometry_candidates=geometry_report.get('candidates',[])
    if not geometry_candidates:
        geometric=base_variant('geometry','Geometry prediction','Repeated features + symmetry + planar continuation')
        geometric['scan_preview']=current['scan_preview']
        geometric['message']='No supported geometric repair from the current measured surface. No object-category template is used.'
        variants.append(geometric)
    for candidate in geometry_candidates:
        kind=candidate.get('pattern_kind','geometry')
        geometric=base_variant('geometry_'+candidate['id'],kind.replace('_',' ').title(),
            'Observed donor transfer or planar continuation; geometric hypothesis')
        geometric['scan_preview']=current['scan_preview']
        geometric['part_preview']=candidate.get('print_preview') or candidate['preview']
        validation=candidate.get('validation',{})
        files=validation.get('files',[])+[candidate['id']+'_validation.json','pattern_hypotheses.json']
        geometric['printable']=bool(validation.get('watertight') and files and all((output_dir/n).is_file() for n in files))
        geometric['print_files']=files if geometric['printable'] else []
        geometric['status']='proposal_needs_review' if geometric['printable'] else 'surface_only'
        geometric['message']='Provisional geometry. Confirm the region is actually damaged; hidden surfaces and physical fit remain unverified.'
        geometric['metrics']={'support_score':candidate.get('support_score'),'assumptions':candidate.get('assumptions',[])}
        variants.append(geometric)
    stereo=base_variant('photo','Photo stereo','COLMAP-aligned, cross-pair checked stereo')
    report=base.get('photo_recovery',{})
    if (output_dir/'photo_recovered_surface_m.ply').exists():
        mesh=o3d.io.read_triangle_mesh(str(output_dir/'photo_recovered_surface_m.ply'))
        stereo['scan_preview']=mesh_preview(mesh,output_dir/'photo_scan.json')
        stereo['status']='surface_only' if stereo['scan_preview'] else 'needs_more_evidence'
    stereo['metrics']={k:report.get(k) for k in ['accepted_pixels','cross_pair_supported_pixels','surface_triangles']}
    stereo['metrics']['processing_shared_with_current']=True
    stereo['message']='Only photo samples supported across independent pairs are shown. No missing material is inferred.'
    variants.append(stereo)
    tracked=base_variant('tracked','Tracked repeated feature','Image tracks + multiview square fit + observed donor outline')
    tracked['message']='This baseline supports a regular cube face with a missing edge; it is not a general-object model.'
    t=time.monotonic();progress('reconstructing',.66,'Testing tracked structural repair')
    with TemporaryDirectory(prefix='reversecad-compare-') as temporary:
        private=Path(temporary)
        pose_file=output_dir/'photo_camera_poses.json'
        if pose_file.exists():
            poses=json.loads(pose_file.read_text())['poses'];fixed=[{**f,'pose':np.array(poses[f['frame_id']])} for f in frames if f['frame_id'] in poses]
            try:
                folder=private/'tracked';folder.mkdir()
                result=repair_from_faces(fixed,scan_dir,folder)
                copy_result(folder,output_dir,tracked,result)
                tracked['message']='Estimated exterior from tracked repeated features. Cube-specific structural assumption; fine relief and fit are unverified.'
            except (ValueError,RuntimeError) as exc:tracked['message']=str(exc)
        else:tracked['message']='A shared photo camera frame is required for the tracked-structure baseline.'
        tracked['seconds']=time.monotonic()-t;variants.append(tracked)
        # Neural reconstruction is paused after failing the real-reference benchmark.
        # Keep the offline helpers above for research, but never launch a learned
        # model or advertise learned variants from an app comparison request.
    prototypes=[v for v in variants if v['printable'] and v['part_preview']]
    prototypes.sort(key=lambda v:not v['id'].startswith('geometry_'))
    selected=prototypes[0]['id'] if prototypes else next((v['id'] for v in variants if v['scan_preview'] and v['status']=='surface_only'),current['id'])
    summary={'schema_version':1,'scan_id':manifest['scan_id'],'input_revision':base.get('input_revision'),
             'variants':variants,'suggested_variant_id':selected,'verified_winner':None,
             'conclusion':('A reviewable exterior prototype is available. No method has independently validated fit.' if prototypes else 'No reliable replacement was established. Compare the recovered surfaces; no verified winner.'),
             'seconds':time.monotonic()-start,'physical_fit':'not_tested'}
    write_json(output_dir/'comparison.json',summary)
    base['comparison']=summary
    write_json(output_dir/'reconstruction.json',base)
    return base
