#!/usr/bin/env python3
"""Offline registration comparison; outputs are diagnostic, never manufacturing claims."""
import sys,json,copy,time
from pathlib import Path
import numpy as np
from reversecad.reconstruction import _load_package,_prepare,_depth_consistency,_rgb_consistency,_tsdf
from reversecad.geometry import transform_points
import argparse
parser=argparse.ArgumentParser(description='Compare photo and colored-depth registration on an immutable capture')
parser.add_argument('scan',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('--method',choices=['colmap','open3d'],required=True)
args=parser.parse_args()
SCAN=args.scan; OUT=args.output; OUT.mkdir(parents=True,exist_ok=True)
m,raw,segs=_load_package(SCAN)
frames,*_=_prepare(SCAN,raw,segs,{},'rgb_assisted')
# Bound the expensive all-pairs Open3D benchmark; production COLMAP is bounded separately.
frames=[frames[i] for i in np.unique(np.linspace(0,len(frames)-1,min(24,len(frames)),dtype=int))]
method=args.method
start=time.time()
if method=='colmap':
 from reversecad.photo_alignment import align_photos
 out=OUT/'colmap';out.mkdir(exist_ok=True)
 corrected,alignment=align_photos(SCAN,frames,raw,out)
 (out/'alignment.json').write_text(json.dumps(alignment,indent=2))
 if not corrected:
  print(json.dumps(alignment));sys.exit(2)

else:
 import open3d as o
 out=OUT/'open3d';out.mkdir(exist_ok=True)
 clouds=[]
 for f in frames:
  c=o.geometry.PointCloud();c.points=o.utility.Vector3dVector(f['points']);c.colors=o.utility.Vector3dVector(f['colors']);c=c.voxel_down_sample(.001);c.estimate_normals(o.geometry.KDTreeSearchParamHybrid(radius=.006,max_nn=30));clouds.append(c)
 reg=o.pipelines.registration;graph=reg.PoseGraph()
 for i in range(len(frames)):graph.nodes.append(reg.PoseGraphNode(np.eye(4)))
 for i in range(len(frames)):
  for j in range(i+1,len(frames)):
   t=np.eye(4)
   try:
    for dist in [.02,.01,.005]:
     r=reg.registration_colored_icp(clouds[i],clouds[j],dist,t,reg.TransformationEstimationForColoredICP(),reg.ICPConvergenceCriteria(max_iteration=40));t=r.transformation
    if r.fitness<.35:continue
    info=reg.get_information_matrix_from_point_clouds(clouds[i],clouds[j],.005,t)
    graph.edges.append(reg.PoseGraphEdge(i,j,t,info,uncertain=True))
    print('PAIR',i,j,r.fitness,r.inlier_rmse,flush=True)
   except RuntimeError:pass
 # Only optimize a connected graph; never pretend disconnected frames registered.
 import networkx as nx
 links=nx.Graph();links.add_nodes_from(range(len(frames)))
 for edge in graph.edges:links.add_edge(edge.source_node_id,edge.target_node_id,edge=edge)
 component=max(nx.connected_components(links),key=len);order=sorted(component);lookup={old:new for new,old in enumerate(order)}
 poses={order[0]:np.eye(4)};tree=set()
 for a,b in nx.bfs_edges(links.subgraph(component),order[0]):
  e=links[a][b]['edge'];t=e.transformation if e.source_node_id==a else np.linalg.inv(e.transformation)
  poses[b]=poses[a]@np.linalg.inv(t);tree.add(tuple(sorted((a,b))))
 new=reg.PoseGraph()
 for old in order:new.nodes.append(reg.PoseGraphNode(poses[old]))
 for a,b,attrs in links.subgraph(component).edges(data=True):
  e=attrs['edge'];new.edges.append(reg.PoseGraphEdge(lookup[e.source_node_id],lookup[e.target_node_id],e.transformation,e.information,uncertain=tuple(sorted((a,b))) not in tree))
 graph=new;frames=[frames[i] for i in order]
 print('CONNECTED',len(frames),flush=True)
 reg.global_optimization(graph,reg.GlobalOptimizationLevenbergMarquardt(),reg.GlobalOptimizationConvergenceCriteria(),reg.GlobalOptimizationOption(max_correspondence_distance=.005,edge_prune_threshold=.15,reference_node=0))
 corrected=[]
 for f,node in zip(frames,graph.nodes):
  g=copy.deepcopy(f);g['pose']=node.pose@f['pose']
  for key in ['points','raw_points']:g[key]=transform_points(f[key],node.pose)
  corrected.append(g)
np.savez(out/'poses.npz',**{f['frame_id']:f['pose'] for f in corrected})
report={'method':method,'seconds':time.time()-start,'frames':len(corrected),'depth_before':_depth_consistency(frames),'depth_after':_depth_consistency(corrected),'rgb_after':_rgb_consistency(corrected)[0]}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
mesh=_tsdf(corrected,.0005,out)
print('Registration diagnostic only; no repair was generated from this benchmark.',flush=True)
