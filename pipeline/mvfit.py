import numpy as np, sys; from PIL import Image; from lib import *
from scipy import ndimage as ndi
IM='refs/'
d=np.load('colored.npz'); V=d['v']; N=d['n']; c=np.load('weld.npz')['v'].mean(0); v=V[::6]
def refmask(ref):
    H,W=ref.shape[:2]; yy,xx=np.mgrid[0:H,0:W]
    X=np.stack([np.ones(H*W),xx.ravel()/W,yy.ravel()/H,(xx.ravel()/W)**2,(yy.ravel()/H)**2,(xx*yy).ravel()/(W*H)],1)
    band=((xx<W*0.15)|(xx>W*0.85)|(yy<H*0.13)|(yy>H*0.87)).ravel()
    bg=np.stack([X@np.linalg.lstsq(X[band],ref[...,k].ravel()[band],rcond=None)[0] for k in range(3)],1).reshape(H,W,3)
    m=np.abs(ref-bg).max(2)>14
    m=ndi.binary_closing(ndi.binary_opening(m,iterations=1),iterations=2)
    lab,n=ndi.label(m); sz=ndi.sum(m,lab,range(1,n+1)); m=ndi.binary_fill_holes(lab==(1+np.argmax(sz)))
    return m
res={}
for name in sys.argv[1:]:
    ref=np.asarray(Image.open(IM+name+'.png').convert('RGB')).astype(float); H,W=ref.shape[:2]
    mask=refmask(ref)
    def mm(yaw,pitch,s,tx,ty):
        p=(v-c)@rot(yaw,pitch).T
        x=np.round(p[:,0]*s+tx).astype(int); y=np.round(-p[:,2]*s+ty).astype(int)
        ok=(x>=0)&(x<W)&(y>=0)&(y<H); m=np.zeros((H,W),bool); m[y[ok],x[ok]]=True
        return ndi.binary_fill_holes(ndi.binary_closing(m,iterations=2))
    def score(prm,ret=False):
        m=mm(*prm); ys=np.where(m.any(1))[0]
        if len(ys)==0: return 0
        mk=mask.copy(); mk[ys.max()+1:]=False        # ignore the display base below the feet
        return (m&mk).sum()/max((m|mk).sum(),1)
    best=(0,None)
    for yaw in np.radians(np.arange(0,360,15)):
        for pitch in np.radians([4,12,20]):
            m0=mm(yaw,pitch,3.5,W/2,H/2); 
            # scale from silhouette heights (mask may include the base: use top + width heuristics, then refine)
            ys0=np.where(m0.any(1))[0]; ysr=np.where(mask.any(1))[0]
            for hfrac in (1.0,0.9):
                s=3.5*(ysr.max()-ysr.min())*hfrac/(ys0.max()-ys0.min())
                m1=mm(yaw,pitch,s,W/2,H/2); ys1=np.where(m1.any(1))[0]; xs1=np.where(m1.any(0))[0]
                # align head top and horizontal centre of the upper half (head)
                top=ysr.min(); headrows=mask[top:top+int((ysr.max()-top)*0.4)]; hx=np.where(headrows.any(0))[0]
                h1=m1[ys1.min():ys1.min()+int((ys1.max()-ys1.min())*0.4)]; hx1=np.where(h1.any(0))[0]
                prm=[yaw,pitch,s,W/2+(hx.mean()-hx1.mean()),H/2+(top-ys1.min())]; sc=score(prm)
                if sc>best[0]: best=(sc,prm)
    sc,prm=best; step=np.array([np.radians(6),np.radians(4),0.12,6,6])
    for it in range(80):
        imp=False
        for i in range(5):
            for sg in (-1,1):
                q=list(prm); q[i]+=sg*step[i]; s2=score(q)
                if s2>sc: sc,prm,imp=s2,q,True
        if not imp:
            step/=2
            if step[3]<0.3: break
    print(name,(W,H),'IoU',round(sc,4),'yaw',round(np.degrees(prm[0])%360,1),'pitch',round(np.degrees(prm[1]),1),'s',round(prm[2],3),'t',round(prm[3],1),round(prm[4],1))
    res[name]=prm; np.save(f'mask_{name}.npy',mask)
    R=rot(prm[0],prm[1]); cen=c-np.linalg.inv(R)@np.array([(prm[3]-W/2)/prm[2],0,-(prm[4]-H/2)/prm[2]])
    rgb,_,_=splat(V,N,yaw=prm[0],pitch=prm[1],scale=prm[2],size=(W,H),center=cen)
    bl=(0.5*ref+0.5*rgb).astype('uint8'); ys,xs=np.where(mask)
    Image.fromarray(bl[max(ys.min()-20,0):ys.max()+20,max(xs.min()-20,0):xs.max()+20]).save(f'mvblend_{name}.png')
np.save('mvfits.npy',res,allow_pickle=True)
