#!/usr/bin/env python3
"""Compare geometry-only and optional live Grok advice on one saved scan.

Example:
  PYTHONPATH=backend .venv/bin/python scripts/benchmark_grok.py \
    --scan-dir var/service/scans/SCAN_ID/capture --output work/grok-check --live

Only --live sends grayscale capture-guide crops to xAI. Raw images and keys
are never written into the comparison summary. Exact fit needs physical checks.
"""
import argparse
import json
import os
from pathlib import Path
from reversecad.reconstruction import reconstruct
from reversecad.visual_adviser import settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if args.live and not settings()['api_key']:parser.error('Set XAI_API_KEY in .env before --live')
    if args.output.exists():parser.error('Choose a new output directory to preserve previous comparisons')
    args.output.mkdir(parents=True)
    runs=[]
    for name,enabled in [('geometry_only',False)]+([('grok',True)] if args.live else []):
        os.environ['REVERSECAD_GROK_ENABLED']='true' if enabled else 'false'
        result=reconstruct(args.scan_dir,args.output/name,{'repair_scope':'cube_exterior'})
        face=result.get('face_repair',{})
        runs.append({'mode':name,'status':result['status'],'piece_count':face.get('piece_count'),
                     'target_cells':face.get('target_cells'),'width_mm':face.get('width_mm'),
                     'elapsed_s':result.get('metrics',{}).get('elapsed_s'),
                     'watertight':face.get('closure',{}).get('watertight',False),
                     'vision_adviser':face.get('vision_adviser'),
                     'physical_fit':'not_tested'})
    summary={'runs':runs,'interpretation':'A live response or closed mesh alone does not prove improved repair accuracy. Compare the ghosts and donor contours with the original photos and removed pieces.'}
    (args.output/'comparison.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
