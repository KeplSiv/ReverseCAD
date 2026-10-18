"""Estimated CAD donors from explicitly associated reference observations.

This path is an image-guided prototype, not photogrammetric measurement. It
keeps reference proportions separate from the scan's inferred metric scale.
It never applies a cube donor to an unrelated object or swaps edge/corner types.
"""
import json
from pathlib import Path
import numpy as np


def _detail_cut(shape, cutter, name, records, probe=None):
    """A requested recess must remove material and leave a valid solid."""
    result = shape.cut(cutter).clean()
    removed = shape.Volume() - result.Volume()
    if removed <= shape.Volume()*1e-7 or not result.isValid() or len(result.Solids()) != 1:
        raise ValueError(f'Reference detail {name} failed solid validation')
    record = {'feature': name, 'removed_volume_mm3': removed}
    if probe is not None:
        record['void_probe_mm'] = list(map(float, probe))
    records.append(record)
    return result


def _profile_wire(plane, points, smooth=False):
    """Closed traced section, retaining smooth molded curves in CAD."""
    import cadquery as cq
    if smooth:
        edge = cq.Edge.makeSpline([plane.toWorldCoords(tuple(p)) for p in points], periodic=True)
        return cq.Wire.assembleEdges([edge])
    return cq.Workplane(plane).polyline(points.tolist()).close().val()


def _reference_details(body, stem, foot, *, spec, width, center, dimensions,
                       inward, root, plane, stem_length, stations, outline, sizes):
    """Visible relief modeled as actual CAD cuts, with estimated depths.

    Image observations live in the associated donor record. No dark pixel is
    automatically treated as a hole, and no unseen through-hole is invented.
    """
    import cadquery as cq
    detail = spec['details']
    required = ['body_scoop_radius', 'body_scoop_offset', 'stem_channel_radius',
                'foot_recess_depth', 'foot_groove_depth']
    if detail.get('version') not in (2,3,4,5) or any(not np.isfinite(detail[k]) or not 0 < detail[k] < .8 for k in required):
        raise ValueError('Invalid reference detail proportions')
    records = []
    refined = detail['version'] >= 5
    # Bowl-shaped inner-side reliefs seen in the oblique body views. These
    # preserve the outer faces and central material supporting the neck.
    for axis in np.flatnonzero(inward):
        normal = np.zeros(3); normal[axis] = np.sign(inward[axis])
        lateral = inward.copy(); lateral[axis] = 0
        c = center + normal*dimensions[axis]*detail['body_scoop_offset'] + lateral*.10*width
        radius = width*detail['body_scoop_radius']
        cutter = cq.Workplane('XY').sphere(radius).val()
        if refined:
            # Oblique references show a broad shallow scallop, not a circular
            # hemispherical bore. The relief stays on the inward side.
            scales = np.full(3, 1.08); scales[axis] = .76
            cutter = cutter.transformGeometry(cq.Matrix([
                [scales[0],0,0,0],[0,scales[1],0,0],[0,0,scales[2],0],[0,0,0,1]]))
        cutter = cutter.translate(tuple(c))
        body = _detail_cut(body, cutter, f'body_concavity_{axis}', records)
    # Longitudinal channels visible on the corner neck. Kept blind at both
    # ends, leaving a continuous core and attachment to the body and foot.
    if spec['piece_type'] == 'corner' and detail.get('neck_channels_supported', True):
        for axis, span in [(plane.xDir, spec['ratios']['stem_width']),
                           (plane.yDir, spec['ratios']['stem_thickness'])]:
            direction = np.array(axis.toTuple())
            for sign in [-1, 1]:
                c = root + inward*stem_length*.12 + direction*sign*span*width*.49
                cut = cq.Solid.makeCylinder(detail['stem_channel_radius']*width,
                                           stem_length*.76, cq.Vector(*c), cq.Vector(*inward))
                stem = _detail_cut(stem, cut, 'neck_channel', records)
    top = stations[-1][0]
    tip = root+inward*top
    top_plane = cq.Plane(origin=tuple(tip), normal=tuple(inward), xDir=plane.xDir)
    def prism(scale, depth, contour=None, floor_scale=1.):
        # Start beyond the tip so the pocket opens to the outside.
        origin = tip+inward*.01*width
        p = cq.Plane(origin=tuple(origin), normal=tuple(-inward), xDir=plane.xDir)
        # Inverting the normal flips local Y; retain the traced footprint.
        points = outline*scale
        if contour is not None:
            from scipy.interpolate import splprep, splev
            raw = np.asarray(spec['foot_outline'],float)
            trace = np.asarray(contour,float)
            if trace.ndim != 2 or trace.shape[1] != 2 or len(trace)<5 or not np.isfinite(trace).all():
                raise ValueError('Invalid reference recess contour')
            trace = np.vstack([trace,trace[0]])
            spline,_ = splprep(trace.T,s=0,per=True)
            trace = np.array(splev(np.linspace(0,1,72,endpoint=False),spline)).T
            points = (trace-(raw.min(0)+raw.max(0))/2)/np.ptp(raw,axis=0)
        points = points*sizes*np.array([1., -1.])
        if not refined:
            return cq.Workplane(p).polyline(points.tolist()).close().extrude(depth+.01*width).val()
        # Rounded draft down to a blind floor; this models the observed
        # molded channel and shallow dish without interpreting dirt as depth.
        centroid = points.mean(0)
        wires = []
        for distance, factor in [(0,1.),(.01*width,1.),
                                 (.01*width+depth*.7,1+(floor_scale-1)*.8),
                                 (.01*width+depth,floor_scale)]:
            section = cq.Plane(origin=tuple(origin-inward*distance),
                               normal=tuple(-inward),xDir=plane.xDir)
            wires.append(_profile_wire(section,centroid+(points-centroid)*factor,True))
        return cq.Solid.makeLoft(wires,ruled=False)
    if spec['piece_type'] == 'corner':
        # IMG_3855: outer lip, deep triangular channel, raised inner ridge,
        # and shallower central dish. These are nested blind recesses.
        depth = detail['foot_groove_depth']*width
        ring = prism(.84, depth, detail.get('channel_outer'), .97).cut(prism(.65, depth+.01*width, detail.get('channel_inner'), 1.035))
        probe_local = outline[0]*sizes*.75
        probe = np.array(top_plane.toWorldCoords(tuple(probe_local)).toTuple())-inward*depth*.4
        foot = _detail_cut(foot, ring, 'triangular_perimeter_channel', records, None if detail.get('channel_outer') else probe)
        depth = detail['foot_recess_depth']*width
        foot = _detail_cut(foot, prism(.53, depth, detail.get('center_outline'), .94), 'central_triangular_recess', records, tip-inward*depth*.4)
    else:
        # IMG_3849/3851/3861: a raised rounded rectangular tab on the foot,
        # with a channel around it. Unlike the corner, this has a solid tip.
        depth = detail['foot_groove_depth']*width
        ring = prism(.64, depth, floor_scale=.96).cut(prism(.39, depth+.01*width, floor_scale=1.04))
        foot = _detail_cut(foot, ring, 'edge_retaining_channel', records)
        boss_width = sizes[0]*.38; boss_height = sizes[1]*.58
        boss_plane = cq.Plane(origin=tuple(tip-inward*.015*width), normal=tuple(inward), xDir=plane.xDir)
        # Round the tab's four upright edges in its own local coordinates.
        local = (cq.Workplane('XY').box(boss_width, boss_height, .12*width,
                 centered=(True,True,False)).edges('|Z').fillet(.06*width).val())
        if refined:
            local = cq.Workplane(obj=local).faces('>Z').edges().fillet(.022*width).val()
        boss = local.moved(boss_plane.location)
        foot = foot.fuse(boss).clean()
        if not foot.isValid() or len(foot.Solids()) != 1:
            raise ValueError('Edge retaining tab is disconnected')
        records.append({'feature':'rounded_edge_retaining_tab','added_volume_mm3':boss.Volume()})
        if detail.get('central_rib_supported'):
            rib_plane = cq.Plane(origin=tuple(tip+inward*.095*width),normal=tuple(inward),xDir=plane.xDir)
            rib = (cq.Workplane('XY').center(0,-.045*width).slot2D(.27*width,.075*width,90)
                   .extrude(.055*width).val().moved(rib_plane.location))
            foot = foot.fuse(rib).clean()
            if not foot.isValid() or len(foot.Solids()) != 1:
                raise ValueError('Edge central rib is disconnected')
            records.append({'feature':'edge_central_rib','added_volume_mm3':rib.Volume()})
    return body, stem, foot, records


def load_reference_set(scan_dir, library=None):
    library = Path(library) if library else Path(__file__).resolve().parents[2] / 'var/reference-pieces/cube.json'
    manifest = Path(scan_dir) / 'manifest.json'
    if not library.is_file() or not manifest.is_file():
        return None
    data = json.loads(library.read_text())
    scan_id = json.loads(manifest.read_text()).get('scan_id')
    if scan_id not in data.get('scan_ids', []):
        return None
    if data.get('schema_version') != 1 or data.get('status') != 'estimated_prototype':
        raise ValueError('Reference library is not an estimated prototype revision')
    return data


def build_reference_solid(boundary, depth, source_cell, spec):
    import cadquery as cq
    import trimesh
    from .face_first import cell_type
    kind = cell_type(source_cell)
    if kind != spec.get('piece_type'):
        raise ValueError('Reference donor type does not match the missing piece')
    params = spec['ratios']
    required = ['body_rounding', 'stem_width', 'stem_thickness', 'stem_length',
                'foot_width', 'foot_thickness', 'shoulder_length', 'rim_height', 'tip_length']
    if 'foot_cap_height' in params: required.append('foot_cap_height')
    if any(not np.isfinite(params[k]) or not 0 < params[k] < 2 for k in required):
        raise ValueError('Reference proportions must be finite positive ratios')
    low, high = np.min(boundary, axis=0), np.max(boundary, axis=0)
    width = float(np.mean(high-low))
    center = np.r_[(low+high)/2, -depth/2]
    inward = np.r_[-(np.array(source_cell, float)-1), -1.]
    inward /= np.linalg.norm(inward)
    radius = min(params['body_rounding']*width, min(*(high-low), depth)*.18)
    body = cq.Workplane('XY').box(float(high[0]-low[0]), float(high[1]-low[1]), depth).edges().fillet(radius).translate(tuple(center)).val()
    # The unseen transition is an explicit idealization. The front face remains
    # outside the cut; the stem points toward the cube interior for every cell.
    cut_distance = (.38 if kind == 'corner' else .22)*width
    root = center + inward*cut_distance
    # Register the connector to the outer faces. OCCT's default plane chooses
    # an arbitrary roll that changes with the donor cell; it is not an assembly
    # orientation. The corner triangle's tip points toward the front face.
    x_direction = None
    if spec.get('assembly_frame') == 'outer_faces':
        front = np.array([0., 0., 1.])
        front -= inward*np.dot(front, inward)
        front /= np.linalg.norm(front)
        x_direction = tuple(np.cross(front, inward) if kind == 'corner' else front)
    plane = cq.Plane(origin=tuple(root), normal=tuple(inward), xDir=x_direction)
    cutter = cq.Workplane(plane).rect(4*width,4*width).extrude(4*width).val()
    body = body.cut(cutter)
    overlap = .04*width
    stem_length = params['stem_length']*width
    stem_plane = cq.Plane(origin=tuple(root-inward*overlap), normal=tuple(inward), xDir=plane.xDir)
    stem = cq.Workplane(stem_plane).ellipse(params['stem_width']*width/2,
                                           params['stem_thickness']*width/2).extrude(stem_length+2*overlap).val()
    refined = spec.get('details', {}).get('version', 0) >= 5
    if refined and kind == 'corner':
        # Flat sides and radiused corners are visible in IMG_3853/3854.
        local = (cq.Workplane('XY').box(params['stem_width']*width,
                 params['stem_thickness']*width,stem_length+2*overlap,
                 centered=(True,True,False)).edges('|Z').fillet(.045*width).val())
        stem = local.moved(stem_plane.location)
    outline = np.asarray(spec['foot_outline'],float)
    if outline.ndim != 2 or outline.shape[1] != 2 or len(outline)<8 or not np.isfinite(outline).all():
        raise ValueError('Reference foot outline is invalid')
    # The traced footprint and its inferred depth are deliberately separate.
    outline = outline-(outline.min(0)+outline.max(0))/2
    outline /= np.ptp(outline,axis=0)
    sizes = np.array([params['foot_width'],params['foot_thickness']])*width
    shoulder=params['shoulder_length']*width; rim=params['rim_height']*width
    z0=stem_length-overlap
    stations=[(z0,.25),(z0+shoulder,1.),(z0+shoulder+rim,1.),
              (z0+shoulder+rim*1.5,.84),(z0+shoulder+rim*2,.84),
              (z0+shoulder+rim*2.5,.94),
              (z0+shoulder+rim*2.5+params['tip_length']*width,.72)]
    if spec.get('details'):
        # Leave an actual floor under the blind pockets, rather than sealing
        # the end with the old tapered flat cap.
        stations = [(z0,.25),(z0+shoulder,1.),(z0+shoulder+rim,1.),
                    (z0+shoulder+rim*1.5,.89),(z0+shoulder+rim*2,.89),
                    (z0+shoulder+rim*2.5,1.),
                    (z0+shoulder+rim*2.5+params.get('foot_cap_height',.14)*width,1.)]
    wires=[]
    for distance,scale in stations:
        section=cq.Plane(origin=tuple(root+inward*distance),normal=tuple(inward), xDir=plane.xDir)
        wires.append(_profile_wire(section,outline*sizes*scale,refined))
    foot=cq.Solid.makeLoft(wires,ruled=True)
    detail_records = []
    if spec.get('details'):
        body, stem, foot, detail_records = _reference_details(
            body, stem, foot, spec=spec, width=width, center=center,
            dimensions=np.r_[high-low,depth], inward=inward, root=root,
            plane=plane, stem_length=stem_length, stations=stations,
            outline=outline, sizes=sizes)
    shape=body.fuse(stem).fuse(foot).clean()
    if not shape.isValid() or len(shape.Solids())!=1:
        raise ValueError('Estimated donor did not form one valid CAD solid')
    vs,fs=shape.tessellate(.04)
    mesh=trimesh.Trimesh([v.toTuple() for v in vs],fs,process=True)
    # OCCT may tessellate opposite sides of a shared curved seam a few
    # nanometers apart. Weld only sub-micron numerical differences in mm.
    mesh.merge_vertices(digits_vertex=6)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals();mesh.units='mm'
    if not mesh.is_volume or mesh.body_count!=1:
        raise ValueError(f'Estimated donor mesh is not a closed connected volume (watertight={mesh.is_watertight}, components={mesh.body_count})')
    if abs(mesh.volume-shape.Volume())>max(.01,shape.Volume()*.01):
        raise ValueError('Reference mesh volume disagrees with CAD solid')
    evidence={'reference_prototype':True,'piece_type':kind,'reference_images':spec['images'],
              'method':'image_guided_parametric_approximation','scale_source':'existing_scan_donor_width',
              'reference_ratios':params,'ratio_source':spec['ratio_source'],
              'estimated_features':['rounded body','inward stem','tapered shoulder','retaining foot','rim relief'],
              'limitations':['Reference proportions and perspective corrections are approximate.',
                             'Unseen surfaces and groove depth are idealized.',
                             'Mechanical clearance, assembly motion and physical fit have not been tested.']}
    if detail_records:
        evidence['detail_revision'] = spec['details']['version']
        evidence['detail_operations'] = detail_records
        evidence['detail_observations'] = spec['details']['observations']
        evidence['recesses_are_blind'] = True
        evidence['estimated_features'] += sorted({r['feature'] for r in detail_records})
    return mesh,shape,evidence


def cad_surface_preview(shape):
    """Render each CAD face with its own analytic normals.

    Sharp seams must not share a smoothed normal. This render mesh is separate
    from the welded, watertight export mesh and contains no photo texture.
    """
    vertices, triangles, normals = [], [], []
    for face in shape.Faces():
        vs, fs = face.tessellate(.04)
        offset = len(vertices)
        vertices.extend(v.toTuple() for v in vs)
        triangles.extend(tuple(i+offset for i in f) for f in fs)
        if face.geomType() == 'PLANE':
            normals.extend([face.normalAt().toTuple()]*len(vs))
        else:
            # Tessellation already carries surface UV coordinates. Reprojecting
            # every vertex onto a B-spline surface is slow and unnecessary.
            from OCP.BRep import BRep_Tool
            from OCP.BRepGProp import BRepGProp_Face
            from OCP.TopLoc import TopLoc_Location
            from OCP.gp import gp_Pnt, gp_Vec
            poly=BRep_Tool.Triangulation_s(face.wrapped,TopLoc_Location())
            if poly is not None and poly.HasUVNodes():
                evaluator=BRepGProp_Face(face.wrapped)
                for index in range(1,poly.NbNodes()+1):
                    uv=poly.UVNode(index); point=gp_Pnt(); normal=gp_Vec()
                    evaluator.Normal(uv.X(),uv.Y(),point,normal)
                    normal.Normalize()
                    normals.append((normal.X(),normal.Y(),normal.Z()))
            else:
                normals.extend(face.normalAt(v).toTuple() for v in vs)
    return np.asarray(vertices), np.asarray(triangles), np.asarray(normals)


def validate_reference_assembly(shapes):
    """Reject actual solid interpenetration; this does not prove moving fit."""
    pairs = []
    for i, a in enumerate(shapes):
        for j in range(i):
            b = shapes[j]
            overlap = abs(a.intersect(b).Volume())
            tolerance = max(.01, min(a.Volume(), b.Volume())*1e-6)
            pairs.append({'piece_indices':[j,i], 'intersection_volume_mm3':overlap,
                          'numerical_tolerance_mm3':tolerance})
            if overlap > tolerance:
                raise ValueError(f'Reference connectors intersect ({overlap:.2f} mm³). Their assembly geometry needs correction.')
    return {'status':'no_solid_intersections' if pairs else 'single_piece',
            'pairs':pairs, 'physical_fit':'not_tested',
            'scope':'Only proposed pieces at their assembled positions; surviving mechanism and motion are not validated.'}
