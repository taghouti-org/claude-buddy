import numpy as np; from PIL import Image; from lib import *
from scipy import ndimage as ndi
d=np.load('colored.npz'); V=d['v']; c=np.load('weld.npz')['v'].mean(0); v=V[::5]
fits=np.load('mvfits.npy',allow_pickle=True).item(); out={}
for name,p0 in fits.items():
    mask=np.load(f'mask_{name}.npy'); H,W=mask.shape
    def score(prm):
        x,y,_,_=proj(v,c,prm); x=np.round(x).astype(int); y=np.round(y).astype(int)
        ok=(x>=0)&(x<W)&(y>=0)&(y<H); m=np.zeros((H,W),bool); m[y[ok],x[ok]]=True
        m=ndi.binary_fill_holes(ndi.binary_closing(m,iterations=2)); ys=np.where(m.any(1))[0]
        mk=mask.copy(); mk[ys.max()+1:]=False
        return (m&mk).sum()/max((m|mk).sum(),1)
    best=(0,None)
    for D in (150,220,320,500,900,5000):
        prm=list(p0)+[D]; sc=score(prm); step=np.array([np.radians(2),np.radians(3),0.06,4,4,0.25])
        for it in range(60):
            imp=False
            for i in range(6):
                for sg in (-1,1):
                    q=list(prm)
                    if i==5: q[5]=q[5]*np.exp(sg*step[5])
                    else: q[i]+=sg*step[i]
                    s2=score(q)
                    if s2>sc: sc,prm,imp=s2,q,True
            if not imp:
                step/=2
                if step[3]<0.25: break
        if sc>best[0]: best=(sc,prm)
    sc,prm=best; out[name]=prm
    print(name,'IoU',round(sc,4),'yaw',round(np.degrees(prm[0])%360,1),'pitch',round(np.degrees(prm[1]),1),'s',round(prm[2],3),'D',round(prm[5]))
np.save('mvfits2.npy',out,allow_pickle=True)
