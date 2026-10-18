#!/usr/bin/env python3
"""Review an existing observed reconstruction, not a replacement model."""
import argparse,json
from pathlib import Path
from reversecad.scan_reasoning import observed_context,review_scan
p=argparse.ArgumentParser()
p.add_argument('--reconstruction',type=Path,required=True)
p.add_argument('--reference',type=Path,action='append',required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--live',action='store_true')
a=p.parse_args()
r=json.loads(a.reconstruction.read_text())
v=json.loads((a.reconstruction.parent/'scan_preview.json').read_text())
context,views=observed_context(r,v)
a.output.mkdir(parents=True,exist_ok=False)
(a.output/'observed_context.json').write_text(json.dumps(context,indent=2))
for i,data in enumerate(views):(a.output/f'observed_{i}.png').write_bytes(data)
if a.live:
 result=review_scan(r,v,[p.read_bytes() for p in a.reference],consent=True)
 (a.output/'review.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({'status':result['status'],'features':result['observed_features'],'repair_generated':False}))
