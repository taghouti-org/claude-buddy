import numpy as np; from PIL import Image, ImageDraw; from lib import *
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
ref=np.asarray(Image.open('ref.png').convert('RGB')).astype(float)/255; H,W=ref.shape[:2]
mask=ndi.binary_erosion(np.load('refmask.npy'),iterations=2)
d=np.load('weld.npz'); V,F=d['v'],d['f']; N=np.load('vn.npy'); c=V.mean(0)
fits=np.load('fits.npy'); sc,yaw,pitch,s,tx,ty=fits[np.argmax(fits[:,0])]; print('cam',sc,np.degrees(yaw),np.degrees(pitch),s,tx,ty)
# --- drop the base and anything not connected to the figure
ZB=5.3
keepv=V[:,2]>ZB
fk=keepv[F].all(1); F=F[fk]
n=len(V); e=np.concatenate([F[:,[0,1]],F[:,[1,2]]])
nc,lab=connected_components(coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(n,n)),directed=False)
cnt=np.bincount(lab[np.unique(F)],minlength=nc); big=np.argmax(cnt); print('components after base cut',(cnt>0).sum(),'kept verts',cnt[big],'dropped',cnt.sum()-cnt[big])
keepv=lab==big; F=F[keepv[F].all(1)]
remap=-np.ones(n,int); remap[keepv]=np.arange(keepv.sum()); V=V[keepv]; N=N[keepv]; F=remap[F]
# --- project
R=rot(yaw,pitch); p=(V-c)@R.T; nn=N@R.T
px=p[:,0]*s+tx; py=-p[:,2]*s+ty; dep=p[:,1]
xi=np.clip(np.round(px).astype(int),0,W-1); yi=np.clip(np.round(py).astype(int),0,H-1)
zb=np.full(H*W,np.inf); np.minimum.at(zb,yi*W+xi,dep); zb=ndi.minimum_filter(zb.reshape(H,W),3)
vis=(dep<=zb[yi,xi]+0.6)&(nn[:,1]<-0.25)&mask[yi,xi]
print('visible verts',vis.sum(),'of',len(V))
x0=np.clip(np.floor(px).astype(int),0,W-2); y0=np.clip(np.floor(py).astype(int),0,H-2); fx=np.clip(px-x0,0,1)[:,None]; fy=np.clip(py-y0,0,1)[:,None]
col=(ref[y0,x0]*(1-fx)*(1-fy)+ref[y0,x0+1]*fx*(1-fy)+ref[y0+1,x0]*(1-fx)*fy+ref[y0+1,x0+1]*fx*fy)
# --- fill hidden verts from nearest visible ones (3D), smoothed
tree=cKDTree(V[vis]); dist,idx=tree.query(V[~vis],k=6)
w=1/(dist+0.15)**2; w/=w.sum(1,keepdims=True)
col[~vis]=(col[vis][idx]*w[...,None]).sum(1)
np.savez('colored.npz',v=V,f=F,n=N,col=col,vis=vis)
from lib import flat
cc=np.array([c[0],c[1],60.5])
ims=[flat(V,N,col,yaw=a,center=cc) for a in (0,np.pi/2,np.pi,3*np.pi/2)]
sheet=Image.new('RGB',(2400,620)); [sheet.paste(im,(600*i,0)) for i,im in enumerate(ims)]
sheet.resize((1600,413),Image.LANCZOS).save('colored.png'); print('center',c)
