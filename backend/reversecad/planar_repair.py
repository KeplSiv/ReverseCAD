"""Complete boundary damage on a user-declared rectangular, planar part.

RGB supplies the cut boundary. Native depth fits a plane and supplies scale;
no room mesh or cube classifier is involved. Unknown thickness blocks export.
"""
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon, box
from .geometry import scaled_intrinsics, unproject


from .capture_region import capture_bounds


def candidate_contours(image, region=None):
    """Generate contrasting foreground candidates; rectangle evidence ranks them."""
    if region is not None:
        x0,y0,x1,y1 = capture_bounds(region,image.shape)
        # Segment only inside the guide, including threshold/background
        # statistics. Border-touching contours are rejected, never capped.
        for contour in candidate_contours(image[y0:y1,x0:x1]):
            yield contour + [x0,y0]
        return
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    border = np.concatenate([gray[:max(1,h//12)].ravel(), gray[-max(1,h//12):].ravel(),
                             gray[:, :max(1,w//12)].ravel(), gray[:, -max(1,w//12):].ravel()])
    # Brightness contrast locates boundaries. Hue and saturation never decide
    # which material survives or which area is missing.
    distance = np.abs(gray.astype(float)-np.median(border))
    distance = np.clip(distance, 0, 255).astype(np.uint8)
    masks=[]
    for channel in [gray, distance]:
        threshold, mask=cv2.threshold(channel,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        masks.extend([mask,255-mask])
        for offset in (15,30,45):
            _, tighter=cv2.threshold(channel,min(250,threshold+offset),255,cv2.THRESH_BINARY)
            masks.append(tighter)
    seen=[]
    for mask in masks:
        # Close printed ruling and tiny holes, without rounding the torn boundary.
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            area=cv2.contourArea(contour)
            if not .035*h*w < area < .8*h*w:continue
            x,y,bw,bh=cv2.boundingRect(contour)
            if x<3 or y<3 or x+bw>w-3 or y+bh>h-3:continue
            center=np.mean(contour[:,0],axis=0)
            if np.linalg.norm((center-[w/2,h/2])/[w,h])>.32:continue
            signature=(round(x/5),round(y/5),round(bw/5),round(bh/5))
            if signature in seen:continue
            seen.append(signature)
            yield contour[:,0].astype(float)


def supporting_quad(contour,shape):
    boundary=np.zeros(shape[:2],np.uint8);cv2.polylines(boundary,[contour.astype(np.int32)],True,255,1)
    rect=cv2.minAreaRect(contour.astype(np.float32));box=cv2.boxPoints(rect);o=box.mean(0)
    u=box[1]-box[0];u/=np.linalg.norm(u);v=np.array([-u[1],u[0]]);basis=np.column_stack([u,v])
    local=(contour-o)@basis;low=local.min(0);high=local.max(0)
    lines=cv2.HoughLinesP(boundary,1,np.pi/720,25,minLineLength=max(25,(high-low).min()*.2),maxLineGap=12)
    if lines is None:raise ValueError('No straight edges')
    bins=[[],[],[],[]]
    for x1,y1,x2,y2 in lines[:,0]:
        a=np.array([x1,y1],float);b=np.array([x2,y2],float);d=(b-a)@basis;axis=int(abs(d[1])>abs(d[0]));normal=1-axis
        if abs(d[normal])>abs(d[axis])*.35:continue
        mid=((a+b)/2-o)@basis;side=int(mid[normal]>(low[normal]+high[normal])/2)
        extreme=(mid[normal]-low[normal])/(high[normal]-low[normal]);extreme=extreme if side else 1-extreme
        if extreme<.75:continue
        line=np.cross([*a,1.],[*b,1.]);line/=np.linalg.norm(line[:2]);dist=abs(np.column_stack([contour,np.ones(len(contour))])@line)
        close=contour[dist<2.5];proj=(close-a)@(b-a)/np.linalg.norm(b-a)
        length=np.ptp(proj) if len(proj)>1 else 0
        score=length/(high[axis]-low[axis])+extreme*4
        bins[normal*2+side].append((score,line))
    if any(not x for x in bins):raise ValueError('Four supporting edges unresolved')
    ls=[max(x,key=lambda z:z[0])[1] for x in bins]
    def intersect(a,b):p=np.cross(a,b);return p[:2]/p[2]
    return np.array([intersect(ls[0],ls[2]),intersect(ls[1],ls[2]),intersect(ls[1],ls[3]),intersect(ls[0],ls[3])]),ls


def fit_rectangle(outline, size=None):
    """Fit a rectangle only when each original straight edge has surviving support."""
    points=np.asarray(outline,float)
    rect=cv2.minAreaRect(points.astype(np.float32))
    corners=(cv2.boxPoints(rect).astype(float) if size is None else np.array([[0.,0.],[size[0],0.],size,[0.,size[1]]]))
    origin=corners[0];u=corners[1]-origin;v=corners[3]-origin
    width,height=np.linalg.norm(u),np.linalg.norm(v)
    if min(width,height)<=0:raise ValueError('Degenerate outline')
    basis=np.column_stack([u/width,v/height])
    local=(points-origin)@basis
    # Snap floating-point representations of supporting edges. Microscopic
    # strips otherwise join disconnected missing corners around the rectangle.
    for axis, extent in enumerate([width,height]):
        local[abs(local[:,axis]) < extent*1e-7,axis]=0
        local[abs(local[:,axis]-extent) < extent*1e-7,axis]=extent
    observed=Polygon(local).buffer(0)
    if observed.geom_type!='Polygon' or observed.is_empty:raise ValueError('Outline is disconnected')
    rectangle=box(0,0,width,height)
    if observed.difference(rectangle).area > observed.area*.08:
        raise ValueError('The proposed rectangle excludes too much surviving material')
    if observed.area/rectangle.area < .55:raise ValueError('Too much of the original rectangle is missing')
    tolerance=max(min(width,height)*.008,.3)
    support=[]
    # A circle inside a rectangle touches four edges but has no long straight
    # surviving edges. Sum line segments near each supporting line instead.
    for axis,bound,length in [(0,0,height),(0,width,height),(1,0,width),(1,height,width)]:
        total=0.
        for a,b in zip(local,np.roll(local,-1,axis=0)):
            if max(abs(a[axis]-bound),abs(b[axis]-bound))<=tolerance:
                total+=abs(b[1-axis]-a[1-axis])
        support.append(min(1.,total/length))
    if min(support)<.20 or sum(x>.35 for x in support)<3:raise ValueError('Show more of all four original straight edges')
    missing=rectangle.difference(observed)
    regions=list(missing.geoms) if hasattr(missing,'geoms') else [missing]
    patches=[]
    for region in regions:
        if region.geom_type!='Polygon' or region.area<rectangle.area*.003:continue
        # Segmentation jitter along an intact edge is not missing material.
        radius=region.representative_point().distance(observed)
        if radius < min(width,height)*.006:continue
        if not region.intersects(rectangle.boundary):continue
        if region.area>rectangle.area*.35:continue
        region=region.simplify(min(width,height)*.001,preserve_topology=True)
        if not region.is_valid or len(region.interiors):continue
        patches.append(region)
    return {'origin':origin,'basis':basis,'width':width,'height':height,
            'observed':observed.intersection(rectangle),'patches':patches,
            'edge_support':support,'corners':corners}


def analyze_frame(scan_dir, frame):
    from .reconstruction import _read_depth
    import open3d as o3d
    raw=cv2.imread(str(scan_dir/frame['rgb_path']))
    if raw is None:raise ValueError('Photo unavailable')
    factor=min(1.,1200/max(raw.shape[:2]));image=cv2.resize(raw,None,fx=factor,fy=factor)
    k=scaled_intrinsics(frame['intrinsics'],frame['intrinsics_width'],frame['intrinsics_height'],
                        image.shape[1],image.shape[0])
    depth=_read_depth(scan_dir,frame)
    kd=scaled_intrinsics(frame['intrinsics'],frame['intrinsics_width'],frame['intrinsics_height'],
                         depth.shape[1],depth.shape[0],frame.get('depth_calibration_mode','pixel_center'))
    best=None
    depth_rejections=0
    plane_candidates=0
    region = frame.get('capture_region')
    for contour in candidate_contours(image, region):
        from .object_selection import supports_repair_region
        if not supports_repair_region(scan_dir,frame,contour,image.shape):continue
        mask=np.zeros(depth.shape,np.uint8)
        dc=contour*[depth.shape[1]/image.shape[1],depth.shape[0]/image.shape[0]]
        cv2.fillPoly(mask,[np.rint(dc).astype(np.int32)],1)
        mask=cv2.erode(mask,np.ones((5,5),np.uint8))>0
        valid=mask&np.isfinite(depth)&(depth>.08)&(depth<2)
        if frame.get('selection_source') == 'confirmed_same_instance':
            foreground=np.fromfile(scan_dir/frame['mask_path'],dtype=np.uint8).reshape(depth.shape)>0
            valid &= foreground
        if frame.get('confidence_path'):
            confidence=np.fromfile(scan_dir/frame['confidence_path'],dtype=np.uint8).reshape(depth.shape)
            valid &= confidence>=1
        points,_=unproject(depth,kd,np.eye(4),valid)
        if len(points)<70:
            depth_rejections+=1
            continue
        cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
        o3d.utility.random.seed(23)
        plane,ids=cloud.segment_plane(.003,3,300)
        if len(ids)<len(points)*.8:
            depth_rejections+=1
            continue
        plane_candidates+=1
        normal=np.asarray(plane[:3]);distance=float(plane[3]);normal/=np.linalg.norm(normal)
        try:
            quad,lines=supporting_quad(contour,image.shape)
        except ValueError:continue
        if region is not None:
            x0,y0,x1,y1=capture_bounds(region,image.shape)
            if np.any(quad < [x0,y0]) or np.any(quad > [x1-1,y1-1]):continue
        du=np.linalg.inv(k)@np.cross(lines[0],lines[1])
        dv=np.linalg.inv(k)@np.cross(lines[2],lines[3])
        du/=np.linalg.norm(du);dv/=np.linalg.norm(dv)
        if abs(du@dv)>.10:continue
        normal=np.cross(du,dv);normal/=np.linalg.norm(normal)
        distance=-float(np.median(points[ids]@normal))
        if np.median(abs(points[ids]@normal+distance))>.008:continue
        plane_origin=-distance*normal
        a=np.cross(normal,[0.,1.,0.])
        if np.linalg.norm(a)<.1:a=np.cross(normal,[1.,0.,0.])
        a/=np.linalg.norm(a);b=np.cross(normal,a);basis=np.column_stack([a,b])
        rays=np.column_stack([contour,np.ones(len(contour))])@np.linalg.inv(k).T
        denom=rays@normal
        if np.min(abs(denom))<.15:continue
        xyz=rays*(-distance/denom)[:,None]
        qrays=np.column_stack([quad,np.ones(4)])@np.linalg.inv(k).T
        qxyz=qrays*(-distance/(qrays@normal))[:,None]
        width=float((np.linalg.norm(qxyz[1]-qxyz[0])+np.linalg.norm(qxyz[2]-qxyz[3]))*500)
        height=float((np.linalg.norm(qxyz[3]-qxyz[0])+np.linalg.norm(qxyz[2]-qxyz[1]))*500)
        destination=np.array([[0,0],[width,0],[width,height],[0,height]],np.float32)
        homography=cv2.getPerspectiveTransform(quad.astype(np.float32),destination)
        flat=cv2.perspectiveTransform(contour.astype(np.float32)[None],homography)[0]
        try:fit=fit_rectangle(flat,[width,height])
        except ValueError:continue
        if not 15<min(fit['width'],fit['height']) or max(fit['width'],fit['height'])>1500:continue
        photo_area=cv2.contourArea(contour.astype(np.float32))/(image.shape[0]*image.shape[1])
        # Prefer a large central object with four well supported original edges.
        score=min(fit['edge_support'])+photo_area
        if best is None or score>best['score']:
            residual=float(np.median(abs(points[ids]@normal+distance))*1000)
            best={**fit,'score':score,'image':image,'k':k,'plane_origin':plane_origin,
                  'plane_basis':basis,'frame_id':frame['frame_id'],'plane_residual_mm':residual,
                  'plane_inlier_fraction':len(ids)/len(points),'contour_px':contour,'image_from_plane':np.linalg.inv(homography)}
    if best is None and depth_rejections and not plane_candidates:
        raise ValueError('The photo has a candidate outline, but depth does not establish a reliable flat surface. Dimensions and replacement are unresolved; the outline may already be inside the box.')
    if best is None:raise ValueError('Outline not resolved inside the box. Keep the whole flat part inside the box with background visible around every edge.' if region is not None else 'Outline not resolved. Place the flat part on a contrasting surface and show all four original edges.')
    best['capture_region'] = region
    return best


def local_to_pixels(points, fit):
    if 'image_from_plane' in fit:
        return cv2.perspectiveTransform(np.asarray(points,dtype=np.float32).reshape(1,-1,2),fit['image_from_plane'])[0]
    planar=np.asarray(points)@fit['basis'].T+fit['origin']
    xyz=planar@fit['plane_basis'].T/1000+fit['plane_origin']
    q=xyz@fit['k'].T
    return q[:,:2]/q[:,2,None]


def mesh_polygon(polygon, thickness=None):
    import cadquery as cq
    import trimesh
    coords=list(polygon.exterior.coords)[:-1]
    wire=cq.Workplane('XY').polyline(coords).close()
    shape=wire.extrude(thickness).val() if thickness else cq.Face.makeFromWires(wire.val())
    vs,fs=shape.tessellate(.05)
    mesh=trimesh.Trimesh(vertices=[v.toTuple() for v in vs],faces=fs,process=True)
    if thickness:
        mesh.fix_normals()
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.body_count!=1 or mesh.volume<=0:
            raise ValueError('Patch did not form a closed solid')
        expected=polygon.area*thickness
        if abs(mesh.volume-expected)>max(.01,expected*.001):raise ValueError('Export volume disagrees with inferred outline')
    return mesh,shape


def reconstruct_planar(scan_dir, output_dir, manifest, frames, annotations):
    import trimesh
    start=time.monotonic();output_dir=Path(output_dir)
    thickness=annotations.get('planar_thickness_mm')
    if thickness is not None and (not np.isfinite(thickness) or not 0 < thickness <= 100):
        raise ValueError('Thickness must be a measured value greater than zero and no more than 100 mm')
    base={'schema_version':1,'algorithm_version':'planar-1.1','scan_id':manifest['scan_id'],
          'source':manifest.get('source'),'unit':'mm','warnings':[], 'measurements':[], 'primitives':[],
          'input_revision':{'manifest_sha256':hashlib.sha256((scan_dir/'manifest.json').read_bytes()).hexdigest(),
                            'annotations_sha256':hashlib.sha256(json.dumps(annotations,sort_keys=True).encode()).hexdigest()},
          'physical_validation':{'dimension_accuracy':'not_calibrated','printed_fit':'not_tested'}}
    def save(name,value): (output_dir/name).write_text(json.dumps(value,indent=2,allow_nan=False))
    # This path uses one frame's RGB, native depth and camera intrinsics. It
    # never uses ARKit's world pose, so limited world tracking at session
    # startup must not discard an otherwise valid photo. analyze_frame still
    # checks depth confidence, planarity, calibration and supporting edges.
    valid=[f for f in frames if f.get('depth_path') and f.get('tracking_state') in ('normal', 'limited')]
    selected=[valid[i] for i in np.unique(np.linspace(0,len(valid)-1,min(10,len(valid))).astype(int))] if valid else []
    candidates=[];failures=[]
    for f in selected:
        try:candidates.append(analyze_frame(scan_dir,f))
        except ValueError as exc:failures.append(str(exc))
    empty={'vertices':[],'triangles':[],'colors':[],'normals':[],'unit':'mm'}
    if not candidates:
        base.update(status='needs_input',counterpart={'reason':failures[0] if failures else 'Capture one sharp view with native depth.'},
                    metrics={'accepted_frames':0,'elapsed_s':time.monotonic()-start},point_count=0)
        save('scan_preview.json',empty);save('reconstruction.json',base);return base
    candidates.sort(key=lambda x:-x['score']);fit=candidates[0]
    dims=np.sort([fit['width'],fit['height']]);agree=[f for f in candidates if np.max(abs(np.sort([f['width'],f['height']])/dims-1))<.05]
    patches=fit['patches']
    original=fit['image'].copy();overlay=original.copy();layer=original.copy()
    from .preview_display import piece_color
    for i,p in enumerate(patches):cv2.fillPoly(layer,[np.rint(local_to_pixels(p.exterior.coords,fit)).astype(np.int32)],tuple(int(v*255) for v in piece_color(i)[::-1]))
    overlay=cv2.addWeighted(layer,.55,overlay,.45,0)
    boundary=local_to_pixels([[0,0],[fit['width'],0],[fit['width'],fit['height']],[0,fit['height']]],fit)
    cv2.polylines(overlay,[np.rint(boundary).astype(np.int32)],True,(255,220,0),2,cv2.LINE_AA)
    # Result images show exactly the analyzed area. Geometry projection keeps
    # full-image intrinsics; cropping is a presentation step only.
    if fit.get('capture_region') is not None:
        x0,y0,x1,y1=capture_bounds(fit['capture_region'],original.shape)
        original=original[y0:y1,x0:x1];overlay=overlay[y0:y1,x0:x1]
    from .preview_display import orient_preview
    metadata=next(f for f in frames if f['frame_id']==fit['frame_id'])
    original=orient_preview(original,metadata);overlay=orient_preview(overlay,metadata)
    cv2.imwrite(str(output_dir/'planar_original.jpg'),original)
    cv2.imwrite(str(output_dir/'planar_overlay.jpg'),overlay)
    observed,_=mesh_polygon(fit['observed'])
    def preview(m,colors=None):return {'vertices':m.vertices.tolist(),'triangles':m.faces.tolist(),'colors':colors or [],'normals':[],'unit':'mm'}
    save('scan_preview.json',preview(observed))
    all_meshes=[];shapes=[];exports=[]
    for i,p in enumerate(patches):
        mesh,shape=mesh_polygon(p,thickness);all_meshes.append(mesh);shapes.append(shape)
        if thickness:
            name=f'replacement_{i+1}.stl';mesh.export(output_dir/name);exports.append(name)
    if all_meshes:
        combined=trimesh.util.concatenate(all_meshes)
        colors=[piece_color(i) for i,m in enumerate(all_meshes) for _ in m.vertices]
        save('counterpart_preview.json',preview(combined,colors))
    closed=bool(patches and thickness)
    if closed:
        import cadquery as cq
        combined.export(output_dir/'printable_edge.stl')
        combined.units='mm'
        combined.export(output_dir/'printable_edge.3mf')
        for name in ['printable_edge.stl','printable_edge.3mf']:
            restored=trimesh.load(output_dir/name,force='mesh')
            if not restored.is_watertight or restored.body_count!=len(patches):
                raise ValueError('Export did not preserve the closed replacement pieces')
            if not np.allclose(restored.extents,combined.extents,atol=.001):
                raise ValueError('Export changed the replacement dimensions')
        cq.exporters.export(cq.Compound.makeCompound(shapes),str(output_dir/'replacement.step'))
        exports+=['printable_edge.stl','printable_edge.3mf','replacement.step']
    report={'assumption':'Originally rectangular planar part','frame_id':fit['frame_id'],
            'capture_region':fit.get('capture_region'),
            'width_mm':fit['width'],'height_mm':fit['height'],'thickness_mm':thickness,
            'thickness_source':'user_measurement' if thickness else 'unresolved',
            'scale_source':'native_depth_plane_and_calibrated_photo_rays','scale_accuracy':'uncalibrated',
            'plane_median_residual_mm':fit['plane_residual_mm'],'supporting_frames':len(agree),
            'original_edge_support':fit['edge_support'],'piece_count':len(patches),
            'missing_area_mm2':sum(p.area for p in patches),
            'polygons_mm':[list(p.exterior.coords) for p in patches],
            'physical_fit':'not_tested','exports':exports,
            'limitations':['Rectangle is a user-selected design assumption.','The outline follows the visible boundary; fit and material behavior remain untested.','Native depth scale is uncalibrated.']}
    reason=(f'{len(patches)} missing region(s) found. Confirm the rectangular outline.' if patches else 'No substantial missing boundary region found.')
    if patches and not thickness:reason+=' Enter measured thickness to create a closed replacement.'
    base.update(status='proposal_needs_review' if patches else 'complete', planar_repair=report,
                counterpart={'status':'proposal_needs_review','scope':'rectangular_planar_part','geometry_is_estimated':True,
                             'watertight_replacement':closed,'reason':reason,'physical_fit':'not_tested'},
                bounds_mm={'min':[0,0,0],'max':[fit['width'],fit['height'],thickness or 0],
                           'extent':[fit['width'],fit['height'],thickness or 0]},
                metrics={'accepted_frames':len(agree),'elapsed_s':time.monotonic()-start},point_count=len(fit['contour_px']))
    save('planar_repair.json',report);save('counterpart.json',base['counterpart'])
    if closed:save('printable_edge.json',{'watertight':True,'connected_solids':len(patches),'physical_fit':'not_tested','thickness_mm':thickness,'unit':'mm'})
    save('reconstruction.json',base)
    return base
