"""Step 1: read a binary STL, weld duplicate vertices, report connected parts.  usage: prep.py model.stl"""
import sys
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
raw=open(sys.argv[1],'rb'); raw.read(80); n_tri=int.from_bytes(raw.read(4),'little')
t=np.fromfile(raw,dtype=np.dtype([('n','<f4',3),('v','<f4',(3,3)),('a','<u2')]),count=n_tri)['v']   # (n,3,3)
np.save('tris.npy',t)
v=t.reshape(-1,3)
u,inv=np.unique(v,axis=0,return_inverse=True)
f=inv.reshape(-1,3)
print('verts',len(u),'faces',len(f))
n=len(u)
e=np.concatenate([f[:,[0,1]],f[:,[1,2]]])
g=coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(n,n))
nc,lab=connected_components(g,directed=False)
cnt=np.bincount(lab)
order=np.argsort(-cnt)
print('components',nc)
for c in order[:40]:
    m=lab==c; p=u[m]
    print(f'comp {c:5d} verts {cnt[c]:7d} min {np.round(p.min(0),1)} max {np.round(p.max(0),1)}')
print('small comps (<100 verts):',(cnt<100).sum(),'verts in them',cnt[cnt<100].sum())
np.savez('weld.npz',v=u,f=f,lab=lab)
