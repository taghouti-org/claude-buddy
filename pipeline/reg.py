import numpy as np; from PIL import Image; from lib import *
from scipy import ndimage as ndi
r=np.load('rig4.npz'); P,C,f,uv=r['P'],r['C'],r['f'],r['uv']; c0=np.load('weld.npz')['v'].mean(0)
at=np.asarray(Image.open('atlas4.png').convert('RGB')).astype(float)/255; AH,AW=at.shape[:2]
rng=np.random.default_rng(0); b=np.vstack([np.eye(3),rng.dirichlet([1,1,1],22)])
pts=np.einsum('kb,fbi->fki',b,P[f]).reshape(-1,3); u=np.einsum('kb,fbi->fki',b,uv[f]).reshape(-1,2); cc=np.einsum('kb,fbi->fki',b,C[f]).reshape(-1,3)
x=np.clip(u[:,0]*AW-0.5,0,AW-1.001); y=np.clip(u[:,1]*AH-0.5,0,AH-1.001); x0=x.astype(int); y0=y.astype(int); fx=(x-x0)[:,None]; fy=(y-y0)[:,None]
cols=(at[y0,x0]*(1-fx)*(1-fy)+at[y0,x0+1]*fx*(1-fy)+at[y0+1,x0]*(1-fx)*fy+at[y0+1,x0+1]*fx*fy)*cc
fnr=np.cross(P[f[:,1]]-P[f[:,0]],P[f[:,2]]-P[f[:,0]]); fnr/=np.maximum(np.linalg.norm(fnr,axis=1,keepdims=True),1e-12); fnr=np.repeat(fnr,len(b),0)
fits=np.load('mvfits8.npy',allow_pickle=True).item()
def render(prm,w,h):
    X,Y,D,R=proj(pts,c0,prm); xi=np.round(X).astype(int); yi=np.round(Y).astype(int); nn=fnr@R.T
    ok=(xi>=0)&(xi<w)&(yi>=0)&(yi<h)&(nn[:,1]<0.15); idx=np.where(ok)[0]; pix=yi[idx]*w+xi[idx]
    o=np.lexsort((D[idx],pix)); pix=pix[o]; idx=idx[o]; first=np.r_[True,pix[1:]!=pix[:-1]]
    ii=-np.ones(w*h,int); ii[pix[first]]=idx[first]; ii=ii.reshape(h,w); m=ii>=0; sil=ndi.binary_fill_holes(ndi.binary_closing(m,iterations=2))
    _,(iy,ix)=ndi.distance_transform_edt(~m,return_indices=True); img=cols[ii[iy,ix]]; return img,sil
def histmatch(a,am,bimg,bm):
    out=a.copy()
    for k in range(3):
        sa=np.sort(a[...,k][am]); sb=np.sort(bimg[...,k][bm]); q=np.searchsorted(sa,a[...,k][am])/max(len(sa),1)
        out[...,k][am]=np.interp(q,np.linspace(0,1,len(sb)),sb)
    return out
def resize(img,s):
    if s==1: return img
    h,w=img.shape[:2]; return np.asarray(Image.fromarray((np.clip(img,0,1)*255).astype('uint8')).resize((w//s,h//s),Image.LANCZOS)).astype(float)/255
def refine(A,Bi,fl,r,p,lam):
    h,w=A.shape[:2]; yy,xx=np.mgrid[0:h,0:w].astype(float); best=np.full((h,w),np.inf); out=fl.copy()
    for dv in range(-r,r+1):
        for du in range(-r,r+1):
            co=[yy+fl[1]+dv,xx+fl[0]+du]; d=0
            for k in range(3): d=d+(A[...,k]-ndi.map_coordinates(Bi[...,k],co,order=1,mode='nearest'))**2
            cost=ndi.uniform_filter(d,p)+lam*(du*du+dv*dv); better=cost<best; best[better]=cost[better]; out[0][better]=(fl[0]+du)[better]; out[1][better]=(fl[1]+dv)[better]
    return out
for name,prm in fits.items():
    ref=np.asarray(Image.open(f'ref8/{name}.png').convert('RGB')).astype(float)/255; bm=np.load(f'mask_{name}.npy'); h,w=bm.shape
    A,am=render(prm,w,h); bgc=np.median(ref[~bm],axis=0); A=histmatch(A,am,ref,bm); A[~am]=bgc
    fl=np.zeros((2,h//4,w//4))
    for s,rr,pp,sig in ((4,5,9,3.5),(2,2,13,5.0),(1,1,17,7.0)):
        As,Bs=resize(A,s),resize(ref,s); hh,ww=As.shape[:2]
        if fl.shape[1:]!=(hh,ww):
            fl=np.stack([np.asarray(Image.fromarray(fl[k].astype('float32')).resize((ww,hh),Image.BILINEAR))*2 for k in range(2)])
        for it in range(2):
            fl=refine(As,Bs,fl,rr,pp,0.0012); fl=np.stack([ndi.gaussian_filter(fl[k],sig) for k in range(2)])
    yy,xx=np.mgrid[0:h,0:w].astype(float); Bw=np.stack([ndi.map_coordinates(ref[...,k],[yy+fl[1],xx+fl[0]],order=3,mode='nearest') for k in range(3)],-1).clip(0,1)
    diff=np.abs(np.stack([ndi.gaussian_filter(A[...,k],3)-ndi.gaussian_filter(Bw[...,k],3) for k in range(3)],-1)).max(-1)
    bad=ndi.binary_dilation(diff>0.25,iterations=1)&am
    Image.fromarray((Bw*255).astype('uint8')).save(f'ref9/{name}.png'); np.save(f'mask9_{name}.npy',am); np.save(f'bad9_{name}.npy',bad)
    print(name,'flow |max|',np.abs(fl).max().round(1),'mean',np.abs(fl).mean().round(2),'bad share of figure',round(bad.sum()/am.sum(),3))
    vis=Bw.copy(); vis[bad]=vis[bad]*0.4+np.array([1,0,1])*0.6
    sh=np.concatenate([A,ref,Bw,vis],1); Image.fromarray((sh*255).astype('uint8')).save(f'ref9/dbg_{name}.png')
