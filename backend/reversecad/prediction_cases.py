"""Deterministic held-out geometry. No cases or dimensions enter the predictor."""
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation


def box(size,at):
    m=trimesh.creation.box(size);m.apply_translation(at)
    for _ in range(2):
        v,f=trimesh.remesh.subdivide(m.vertices,m.faces);m=trimesh.Trimesh(v,f,process=True)
    return m


def planar(broken):
    n=20
    v=np.array([[x,y,0] for y in np.linspace(-20,20,n+1) for x in np.linspace(-25,25,n+1)])
    faces=[];held=[]
    for y in range(n):
        for x in range(n):
            a=y*(n+1)+x;b=a+1;c=a+n+1;d=c+1
            dest=held if 8<=x<12 and 8<=y<12 else faces
            dest.extend([[a,b,d],[a,d,c]])
    truth=trimesh.Trimesh(v,held,process=True);truth.remove_unreferenced_vertices()
    observed=trimesh.Trimesh(v,faces if broken else faces+held,process=True);observed.remove_unreferenced_vertices()
    return observed,truth


def make_case(kind, broken=True, orientation=0, scale=1):
    if kind=='planar':observed,truth=planar(broken)
    else:
        if kind=='rail':
            base=box([60,10,2],[0,0,0]);features=[box([2,8,5],[x,0,3]) for x in [-24,-12,0,12,24]];missing=2
        elif kind=='bracket':
            base=trimesh.util.concatenate([box([40,8,2],[0,0,0]),box([8,4,8],[0,-2,5]),box([4,4,3],[0,3,2])]);features=[]
            for x in [-15,15]:
                m=trimesh.creation.cylinder(radius=3,height=5,sections=32);m.apply_translation([x,1,3]);features.append(m)
            missing=1
        elif kind=='radial':
            base=trimesh.creation.cylinder(radius=10,height=2,sections=64);features=[]
            for i in range(8):
                m=trimesh.util.concatenate([trimesh.creation.cylinder(radius=1.2,height=3,sections=24),trimesh.creation.cylinder(radius=1.6,height=.4,sections=24)])
                m.apply_translation([12*np.cos(i*np.pi/4),12*np.sin(i*np.pi/4),0]);features.append(m)
            missing=0
        elif kind=='asymmetric':
            base=trimesh.creation.icosphere(subdivisions=2)
            v=base.vertices.copy();v[:,0]*=1.1+.3*v[:,1];v[:,2]*=.6+.2*v[:,0];base.vertices=v*10
            features=[];missing=-1
        else:raise ValueError(kind)
        observed=trimesh.util.concatenate([base]+[m for i,m in enumerate(features) if not broken or i!=missing])
        truth=features[missing].copy() if features else None
    rotation=Rotation.from_rotvec(np.array([.3,-.5,.2])*(orientation+1)).as_matrix()
    for m in [observed,truth]:
        if m is not None:m.vertices=(m.vertices@rotation.T)*scale+np.array([.1,-.2,.3])
    return observed,truth
