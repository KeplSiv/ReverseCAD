"""Versioned sparse assets. Raw bytes are authoritative; decoded JSON is derived."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .decoder import decode_packet, FormatError
from ..contracts import finite, safe_asset_path
from ..geometry import rigid_transform

WIDE = 'AVCaptureDeviceTypeBuiltInWideAngleCamera'
PRIMARY_SHA256 = '3ffa40811f65fa2037a37e76b1dae773461b726a6ca1689831bbf430862875f2'


def clean_json(value):
    if isinstance(value, dict): return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [clean_json(v) for v in value]
    if isinstance(value, np.ndarray): return clean_json(value.tolist())
    if isinstance(value, np.generic): return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value): return None
    return value


def write_json(path, value):
    path = Path(path)
    path.write_text(json.dumps(clean_json(value), indent=2, allow_nan=False) + '\n')


def asset(root, name):
    safe_asset_path(name)
    path = Path(root) / name
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Sparse asset escapes capture root')
    return path


def load_packets(root, extension):
    """Never accumulate/stale-fill bank addresses. Every row keeps its own packet PTS."""
    path = asset(root, extension['packet_path'])
    if path.stat().st_size > 32 * 1024**2: raise ValueError('Sparse stream exceeds 32 MiB')
    raw = path.read_bytes()
    events_path = asset(root, extension['event_path'])
    if events_path.stat().st_size > 32 * 1024**2: raise ValueError('Sparse journal exceeds 32 MiB')
    events = [finite(json.loads(x)) for x in events_path.read_text().splitlines() if x.strip()]
    packets, cursor, last, sequences = [], 0, -math.inf, set()
    for event in events:
        if event.get('event') != 'pointCloudSampleBuffer': continue
        if 'seriesOffset' not in event: continue  # explicitly failed/dropped callback, retained in journal
        start, size = event['seriesOffset'], event['seriesBytes']
        if type(start) is not int or type(size) is not int or start != cursor or not 128 <= size <= 8*1024**2:
            raise FormatError('Unindexed, overlapping or invalid sparse byte interval')
        if start+size > len(raw): raise FormatError('Sparse packet extends beyond stream')
        packet = decode_packet(raw[start:start+size])
        if packet.sha256 != event.get('sha256'): raise FormatError('Sparse packet SHA-256 mismatch')
        if packet.to_bytes() != packet.raw: raise FormatError('Lossless sparse decoder round trip failed')
        cursor += size
        pts = event.get('pts')
        seq = event.get('sequence')
        if type(seq) is not int or seq in sequences: raise FormatError('Repeated/missing sparse packet identity')
        sequences.add(seq)
        if not isinstance(pts, (float,int)) or not math.isfinite(pts) or pts <= last:
            raise FormatError('Sparse source timestamps must be finite and strictly increasing')
        last = pts
        if event.get('sensorMetadata',{}).get('PortType') != 'PortTypeBackSparseTimeOfFlight':
            raise FormatError('Sparse packet source is not identified as BackSparseTimeOfFlight')
        packets.append((event,packet))
    if cursor != len(raw): raise FormatError('Sparse stream has unindexed trailing bytes')
    return packets


def validate_extension(root, manifest, frames):
    ext = manifest.get('sparse_capture')
    if ext is None: return None
    if not isinstance(ext,dict) or ext.get('schema_version') != 1 or ext.get('mode') != 'sparse_range_rgb':
        raise ValueError('Unsupported sparse capture extension')
    if ext.get('status') not in ('capturing','available','unavailable'):
        raise ValueError('Invalid sparse capture capability status')
    for key in ('packet_path','event_path','calibration_path'):
        if not isinstance(ext.get(key),str): raise ValueError('Sparse capture is missing '+key)
        asset(root,ext[key])
    cal = finite(json.loads(asset(root,ext['calibration_path']).read_text()))
    if cal.get('schema_version') != 1: raise ValueError('Unsupported sparse calibration schema')
    if cal.get('T_sparse_camera') is not None:
        if cal.get('direction') != 'camera_cv_to_sparse' or cal.get('translation_unit') != 'mm' or cal.get('layout') != 'column_major':
            raise ValueError('Sparse transform requires explicit direction, units and column layout')
        rigid_transform(cal['T_sparse_camera'])
        if cal.get('camera_type') != WIDE: raise ValueError('Extrinsics are not for the physical rear wide camera')
    packets = load_packets(root,ext)
    last_rgb_time = -math.inf
    for f in frames:
        row = f if isinstance(f,dict) else f.model_dump()
        sensor = row.get('sensor_observation')
        if not isinstance(sensor,dict): raise ValueError('Sparse RGB frame is missing sensor observation metadata')
        for key in ('source_timestamp_s','arrival_timestamp_s'):
            value = sensor.get(key)
            if key == 'arrival_timestamp_s' and value is None: continue
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Sparse RGB source/arrival time is missing or nonfinite')
        if sensor.get('clock') != 'host_monotonic_seconds': raise ValueError('Sparse/RGB clock relation is unknown')
        if sensor['source_timestamp_s'] <= last_rgb_time:
            raise ValueError('RGB source timestamps must be strictly increasing')
        last_rgb_time = sensor['source_timestamp_s']
        originals = sensor.get('original_plane_paths')
        if originals is not None:
            hashes = sensor.get('pixel_sha256', [])
            if len(originals) != 2 or len(hashes) != 2:
                raise ValueError('Original NV12 image requires two planes and hashes')
            for index, (name, expected) in enumerate(zip(originals, hashes)):
                path = asset(root, name)
                size = row['rgb_width'] * row['rgb_height'] // (2 if index else 1)
                if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError('Original camera plane size/hash mismatch')
    return ext,cal,packets


def decoded_records(packets):
    for event,packet in packets:
        for slot in range(packet.count):
            fields={name:values[slot] for name,values in packet.fields.items()}
            xyz=np.asarray(fields['points'][:3],float); r=float(fields['euclideanDistances'])
            reasons=[]
            if not np.isfinite(xyz).all() or not math.isfinite(r): reasons.append('nonfinite_geometry')
            elif r<=0 or np.linalg.norm(xyz)<=0: reasons.append('nonpositive_range')
            elif abs(np.linalg.norm(xyz)-r)>max(.01,r*1e-5): reasons.append('range_xyz_disagreement')
            if not math.isfinite(fields['confidences']) or fields['confidences']<=0: reasons.append('nonpositive_or_invalid_quality')
            yield {'id':f"p{event['sequence']}:s{slot}", 'sequence':event['sequence'],
                   'timestamp_s':event['pts'], 'arrival_timestamp_s':event.get('host'),
                   'packet_sha256':packet.sha256, 'slot':slot, 'fields':fields,
                   'valid_for_geometry':not reasons,'invalid_reasons':reasons,
                   'validity_semantics':'analysis checks; unknown flag bits preserved, not a hardware-validity claim'}


def camera_point(xyz_mm, calibration):
    T=rigid_transform(calibration['T_sparse_camera'])
    return (np.asarray(xyz_mm)-T[:3,3])@T[:3,:3]/1000


def timing_report(packets):
    times=np.array([e['pts'] for e,p in packets]); gaps=np.diff(times)
    return {'packets':len(packets),'slots':sum(p.count for e,p in packets),
            'maximum_packet_gap_s':float(gaps.max()) if len(gaps) else None,
            'packet_gaps_over_50ms':int((gaps>.05).sum()),
            'clock':'recorded host monotonic seconds', 'per_spot_exposure_offset':'unknown; packet PTS used without inventing per-slot times',
            'stale_address_carry_forward':False,'source_is_computed_range':True,'raw_photon_histograms':False}
