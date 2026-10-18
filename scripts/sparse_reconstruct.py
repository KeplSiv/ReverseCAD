#!/usr/bin/env python3
"""Import archived fixtures or run the production reconstruction and baseline."""
import argparse
import json
from pathlib import Path
import time
from reversecad.sparse.capture import write_json

p=argparse.ArgumentParser(description=__doc__)
sub=p.add_subparsers(dest='command',required=True)
a=sub.add_parser('import-prelude');a.add_argument('source',type=Path);a.add_argument('output',type=Path);a.add_argument('--region',nargs=4,type=float)
a=sub.add_parser('run');a.add_argument('scan',type=Path);a.add_argument('output',type=Path);a.add_argument('--compare',action='store_true');a.add_argument('--annotations',type=Path)
a=p.parse_args()
if a.command=='import-prelude':
 from reversecad.sparse.import_prelude import import_recording
 print(json.dumps(import_recording(a.source,a.output,a.region),indent=2))
else:
 from reversecad.service import validate_capture
 from reversecad.reconstruction import reconstruct
 if a.output.exists():p.error('Use a fresh output directory; previous results are preserved')
 manifest=json.loads((a.scan/'manifest.json').read_text());validate_capture(a.scan,manifest,512*1024**2)
 annotations=json.loads(a.annotations.read_text()) if a.annotations else {'repair_scope':'general'}
 result=reconstruct(a.scan,a.output,annotations)
 if a.compare:
  start=time.monotonic()
  baseline=reconstruct(a.scan,a.output/'baseline',annotations,stage='raw_depth_pose')
  keys=['status','point_count','bounds_mm','measurements','warnings','metrics']
  write_json(a.output/'comparison.json',{'identical_capture_checksums':json.loads((a.scan/'checksums.json').read_text()),
    'sparse':{k:result.get(k) for k in keys},'legacy_raw_depth_pose':{k:baseline.get(k) for k in keys},
    'baseline_runtime_s':time.monotonic()-start,'physical_dimensions_reference':None,'printed_fit':'untested'})
 print(json.dumps({k:result.get(k) for k in ['status','point_count','bounds_mm','warnings','metrics']},indent=2))
