#!/usr/bin/env python3
"""Prepare CAD evidence locally; --live explicitly sends evidence to Grok."""
import argparse,json
from pathlib import Path
from reversecad.cad_review import context_from_program,context_from_step,review_context,render_shape

def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--step',type=Path);source.add_argument('--program',type=Path)
    p.add_argument('--reference',type=Path,action='append',default=[])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--live',action='store_true')
    a=p.parse_args()
    if a.output.exists():p.error('Output directory must be new')
    if len(a.reference)>4:p.error('At most four selected reference views')
    context=context_from_step(a.step) if a.step else context_from_program(json.loads(a.program.read_text()))
    context['reference_note']='Provided photos are references; exact camera correspondence has not been established.'
    a.output.mkdir(parents=True)
    (a.output/'cad_context.json').write_text(json.dumps(context,indent=2))
    (a.output/'cad_source.py').write_text(context['cadquery_source'])
    if a.step:
        import shutil
        shutil.copyfile(a.step,a.output/'input.step')
    if a.step:
        import cadquery as cq
        shape=cq.importers.importStep(str(a.step)).val()
    else:
        from reversecad.cad_program import execute_cube_program
        shape=execute_cube_program(context['program'])[0].val()
    renders=render_shape(shape)
    for i,data in enumerate(renders): (a.output/f'cad_view_{i+1}.png').write_bytes(data)
    if a.live:
        result=review_context(context,[path.read_bytes() for path in a.reference],consent=True,model_views=renders)
        (a.output/'grok_review.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({'status':result['status'],'geometry_changed':False,'output':str(a.output)}))
    else: print('Local CAD evidence prepared. No provider call made.')

if __name__=='__main__':main()
