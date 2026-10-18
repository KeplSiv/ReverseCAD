#!/usr/bin/env python3
"""Evaluate a synthetic result in its analytic world frame, without fitting scale."""
import argparse
import json
from pathlib import Path
import numpy as np
from reversecad.sparse.capture import write_json
from reversecad.geometry import dot

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('scan', type=Path)
parser.add_argument('result', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
manifest = json.loads((args.scan/'manifest.json').read_text())
if manifest['source'] != 'synthetic':
    parser.error('This evaluator uses synthetic oracle poses; it cannot assess a physical scan')
if args.output.exists():
    parser.error('Use a fresh report path')
frames = [json.loads(line) for line in (args.scan/'frames.jsonl').read_text().splitlines()]
poses = json.loads((args.result/'camera_poses.json').read_text())['poses']
first = next(f for f in frames if f['frame_id'] == poses[0]['frame_id'])
T = np.asarray(first['T_world_camera']).reshape(4, 4, order='F') @ np.diag([1, -1, -1, 1])
oracle = json.loads((Path(__file__).resolve().parents[1]/'fixtures/oracles/calibration_block_rgb_textured.json').read_text())
lo, hi = (np.asarray(oracle['bounds_mm'][name]) for name in ['min', 'max'])
report = {'role': 'synthetic_algorithm_check_not_physical_accuracy',
          'reference': 'fixtures/oracles/calibration_block_rgb_textured.json',
          'reference_bounds_mm': oracle['bounds_mm'],
          'alignment': 'Only the first oracle camera rigid transform; no fitted rotation, translation or scale',
          'printed_fit': 'untested', 'methods': {}}
for name, path in [('sparse', args.result), ('processed_depth_baseline', args.result/'baseline')]:
    result = json.loads((path/'reconstruction.json').read_text())
    points = np.load(path/'points_measurement.npz')['points_m']
    if name == 'sparse':
        points = dot(points, T[:3, :3].T) + T[:3, 3]
    mm = points * 1000
    excess = np.abs(mm - (lo+hi)/2) - (hi-lo)/2
    signed = np.linalg.norm(np.maximum(excess, 0), axis=1) + np.minimum(excess.max(axis=1), 0)
    extent = np.ptp(mm, axis=0)
    report['methods'][name] = {
        'status': result['status'], 'points': len(mm), 'bounds_in_oracle_frame_mm': {'min': mm.min(0), 'max': mm.max(0), 'extent': extent},
        'signed_extent_error_mm': extent - (hi-lo),
        'median_absolute_surface_error_mm': np.median(np.abs(signed)),
        'p95_absolute_surface_error_mm': np.percentile(np.abs(signed), 95),
        'fraction_outside_box_by_over_2mm': np.mean(signed > 2),
        'dimension_gate_pass': bool(np.all(abs(extent - (hi-lo)) <= np.maximum(.5, (hi-lo)*.01))),
        'elapsed_s': result['metrics']['elapsed_s'],
        'surface': result.get('surface'), 'metrics': result['metrics']}
args.output.parent.mkdir(parents=True, exist_ok=True)
write_json(args.output, report)
print(args.output)
