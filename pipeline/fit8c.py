import numpy as np; from PIL import Image; from lib import *
from scipy import ndimage as ndi
src=np.asarray(Image.open('refs/8.png').convert('RGB')).astype(float); H,W=src.shape[:2]
yy,xx=np.mgrid[0:H,0:W]; X=np.stack([np.ones(H*W),xx.ravel()/W,yy.ravel()/H,(xx.ravel()/W)**2,(yy.ravel()/H)**2],1); band=((yy<10)|(yy>H-10)|(xx<8)|(xx>W-8)).ravel()
bg=np.stack([X@np.linalg.lstsq(X[band],src[...,k].ravel()[band],rcond=None)[0] for k in range(3)],1).reshape(H,W,3)
m=np.abs(src-bg).max(2)>13; m=ndi.binary_closing(ndi.binary_opening(m,iterations=1),iterations=2); lab,n=ndi.label(m); sz=ndi.sum(m,lab,range(1,n+1))
blobs=[]
for t in np.argsort(-sz)[:6]+1:
    ys,xs=np.where(lab==t); blobs.append((ys.mean()>H/2,xs.mean(),t))
blobs.sort(); t=blobs[3][2]; mk=ndi.binary_fill_holes(lab==t); ys,xs=np.where(mk); pad=30
bx0,bx1,by0,by1=max(xs.min()-pad,0),min(xs.max()+pad,W),max(ys.min()-pad,0),min(ys.max()+pad,H)
Image.fromarray(src[by0:by1,bx0:bx1].astype('uint8')).save('ref8/g3.png'); np.save('mask_g3.npy',mk[by0:by1,bx0:bx1]); print('g3 panel',bx1-bx0,by1-by0)
d=np.load('colored.npz'); V=d['v']; N=d['n']; c=np.load('weld.npz')['v'].mean(0); v=V[::5]; fits={}
INIT={'h0':0,'h1':325,'h2':91,'h3':180,'g3':270}; K=9
LIM=np.array([[8,0.06,8]]*4+[[22,0.12,15]]*4+[[45,0.12,15]])   # head rows barely move; body rows may; feet may stretch
for name,yaw0 in INIT.items():
    ref=np.asarray(Image.open(f'ref8/{name}.png').convert('RGB')).astype(float); mask=np.load(f'mask_{name}.npy'); h,w=mask.shape
    def score(prm):
        x,y,_,_=proj(v,c,prm); x=np.round(x).astype(int); y=np.round(y).astype(int)
        ok=(x>=0)&(x<w)&(y>=0)&(y<h); mm=np.zeros((h,w),bool); mm[y[ok],x[ok]]=True
        mm=ndi.binary_fill_holes(ndi.binary_closing(mm,iterations=3)); return (mm&mask).sum()/max((mm|mask).sum(),1)
    ysr=np.where(mask.any(1))[0]; xsr=np.where(mask.any(0))[0]; best=(0,None)
    for dyaw in (-20,-10,0,10,20):
        yaw=np.radians(yaw0+dyaw)
        for pitch in np.radians([0,5]):
            x,y,_,_=proj(v,c,[yaw,pitch,1.0,0,0,1e4]); s=(ysr.max()-ysr.min())/(y.max()-y.min())
            x,y,_,_=proj(v,c,[yaw,pitch,s,0,0,1e4])
            prm=[yaw,pitch,s,(xsr.min()+xsr.max())/2-(x.min()+x.max())/2,ysr.min()-y.min(),1e4]; sc=score(prm)
            if sc>best[0]: best=(sc,prm)
    sc,prm=best; step=np.array([np.radians(4),np.radians(3),0.12,8,8,0.4])
    for it in range(100):                                   # rigid camera first
        imp=False
        for i in range(6):
            for sg in (-1,1):
                q=list(prm)
                if i==5: q[5]=float(np.clip(q[5]*np.exp(sg*step[5]),150,2e4))
                else: q[i]+=sg*step[i]
                if abs(np.degrees(q[0])-yaw0)>30: continue
                s2=score(q)
                if s2>sc: sc,prm,imp=s2,q,True
        if not imp:
            step/=2
            if step[3]<0.25: break
    rigid=sc
    x,y,_,_=proj(v,c,prm); wp=np.zeros((K,3)); wp[:,1]=1; prm=list(prm)+[float(y.min()),float(y.max()),wp]; st=np.array([8.0,0.06,6.0])
    for it in range(60):                                    # then let rows slide / widen to follow the drawing
        imp=False
        for k in range(K):
            for j in range(3):
                for sg in (-1,1):
                    w2=prm[8].copy(); w2[k,j]+=sg*st[j]
                    if abs(w2[k,j]-(1 if j==1 else 0))>LIM[k,j]: continue
                    if j==0 and k>0 and (prm[7]-prm[6])/(K-1)+w2[k,0]-w2[k-1,0]<4: continue      # keep rows in order
                    if j==0 and k<K-1 and (prm[7]-prm[6])/(K-1)+w2[k+1,0]-w2[k,0]<4: continue
                    q=prm[:8]+[w2]; s2=score(q)
                    if s2>sc+1e-5: sc,prm,imp=s2,q,True
        if not imp:
            st/=2
            if st[0]<0.5: break
    fits[name]=prm; print(name,'IoU rigid',round(rigid,4),'-> warped',round(sc,4),'yaw',round(np.degrees(prm[0])%360,1),'pitch',round(np.degrees(prm[1]),1),'| dy',prm[8][:,0].round(0),'sx',prm[8][:,1].round(2))
    x,y,dp,R=proj(V,c,prm); xi=np.clip(np.round(x).astype(int),0,w-1); yi=np.clip(np.round(y).astype(int),0,h-1)
    nn=N@R.T; ok=nn[:,1]<0.1; o=np.lexsort((dp[ok],(yi*w+xi)[ok])); pix=(yi*w+xi)[ok][o]; first=np.r_[True,pix[1:]!=pix[:-1]]
    L=np.array([0.3,-0.8,0.5]); L/=np.linalg.norm(L); sh=(np.clip(nn[ok][o][first]@L,0,1)*0.75+0.25)*255
    img=np.zeros((h*w,3)); img[pix[first]]=sh[:,None]; Image.fromarray((0.5*ref+0.5*img.reshape(h,w,3)).astype('uint8')).save(f'ref8/blend_{name}.png')
np.save('mvfits8.npy',{k:fits[k] for k in ('h0','h2','h3','h1','g3')},allow_pickle=True)   # front, side, back, three-quarter, other side
ims=[Image.open(f'ref8/blend_{n}.png') for n in ('h0','h1','h2','h3','g3')]; sh=Image.new('RGB',(sum(i.width for i in ims),max(i.height for i in ims))); x=0
for i in ims: sh.paste(i,(x,0)); x+=i.width
sh.resize((sh.width*2//3,sh.height*2//3)).save('ref8/blends.png')
