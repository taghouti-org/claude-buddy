# ---------- per view: visibility (strict + relaxed), samples
nv=len(views); vis=np.zeros((m,nv),bool); vis2=np.zeros((m,nv),bool); pxy=np.zeros((m,nv,2)); facing=np.zeros((len(f),nv)); vfac=np.zeros((m,nv))
imgs=[]; boxes=[]; cvs=[]
for vi,name in enumerate(views):
    prm=fits[name]; ref=Image.open(IM+name+'.png').convert('RGB'); W,H=ref.size; mask=np.load(f'mask9_{name}.npy'); bad=np.load(f'bad9_{name}.npy')
    X,Y,Dp,R=proj(V,c0,prm); xi=np.clip(np.round(X).astype(int),0,W-1); yi=np.clip(np.round(Y).astype(int),0,H-1)
    ZS=2 if prm[2]>4.5 else 1; Hz,Wz=(H+ZS-1)//ZS,(W+ZS-1)//ZS       # depth map at a density the mesh can fill
    zb=np.full(Hz*Wz,np.inf); np.minimum.at(zb,(yi//ZS)*Wz+xi//ZS,Dp); zb=zb.reshape(Hz,Wz)
    filled=np.isfinite(zb); zf=np.where(filled,zb,1e4)
    _,(iy,ix)=ndi.distance_transform_edt(~filled,return_indices=True); zn=zf[iy,ix]; zz=np.where(ndi.binary_closing(filled,iterations=2),zn,1e4)
    edge=(ndi.maximum_filter(zz,3)-ndi.minimum_filter(zz,3))>4.0; inmask=ndi.binary_erosion(mask,iterations=1)
    unsafe=ndi.binary_dilation(edge,iterations=1); zmin=ndi.minimum_filter(zz,3)
    x,y,dp,_=proj(P,c0,prm); xi=np.clip(np.round(x).astype(int),0,W-1); yi=np.clip(np.round(y).astype(int),0,H-1)
    inside=(x>1)&(x<W-2)&(y>1)&(y<H-2)
    vis[:,vi]=inside&(dp<=zmin[yi//ZS,xi//ZS]+0.9)&(~unsafe[yi//ZS,xi//ZS]|NOEDGE)&inmask[yi,xi]&~bad[yi,xi]; vis2[:,vi]=inside&(dp<=zmin[yi//ZS,xi//ZS]+1.5)&inmask[yi,xi]&~bad[yi,xi]
    if vi==0:                                            # the face front takes the whole front drawing, hidden parts too
        ff_=FORCE&inside&inmask[yi,xi]; vis[:,vi]|=ff_; vis2[:,vi]|=ff_
    pxy[:,vi,0]=x; pxy[:,vi,1]=y
    viewdir=R.T@np.array([0,1.0,0]); facing[:,vi]=np.clip(-(fn@viewdir),0,1); vfac[:,vi]=np.clip(-(NR@viewdir),0,1)
    a=np.asarray(ref).astype(float); _,(iy,ix)=ndi.distance_transform_edt(~inmask,return_indices=True); a=a[iy,ix]
    ys,xs=np.where(mask); pad=10; boxes.append((max(xs.min()-pad,0),max(ys.min()-pad,0),min(xs.max()+pad,W),min(ys.max()+pad,H))); imgs.append(a)
    an=a/255; x0=np.clip(np.floor(x).astype(int),0,W-2); y0=np.clip(np.floor(y).astype(int),0,H-2); fx=np.clip(x-x0,0,1)[:,None]; fy=np.clip(y-y0,0,1)[:,None]
    cvs.append(an[y0,x0]*(1-fx)*(1-fy)+an[y0,x0+1]*fx*(1-fy)+an[y0+1,x0]*(1-fx)*fy+an[y0+1,x0+1]*fx*fy)
    print('view',name,'sees verts',round(vis[:,vi].mean(),3))
# ---------- match tones between screenshots (front view is the reference)
acc_c=np.zeros((m,3)); acc_w=np.zeros(m)
for vi in TONE:
    w=np.where(vis[:,vi],vfac[:,vi]**4,0)
    both=(acc_w>0.05)&(w>0.05)
    if both.sum()>500:
        refc=acc_c[both]/acc_w[both][:,None]; gain=np.clip(np.median((refc+0.02)/(cvs[vi][both]+0.02),axis=0),0.75,1.35)
        cvs[vi]=np.clip(cvs[vi]*gain,0,1); imgs[vi]=np.clip(imgs[vi]*gain,0,255); print('view',views[vi],'gain',gain.round(3),'on',int(both.sum()))
    acc_c+=cvs[vi]*w[:,None]; acc_w+=w
crops=[]
for vi in range(nv):
    bx0,by0,bx1,by1=boxes[vi]; crop=Image.fromarray(imgs[vi][by0:by1,bx0:bx1].astype('uint8'))
    crop=crop.resize((crop.width*UP,crop.height*UP),Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.6*UP/2,percent=70 if UP==1 else 120,threshold=2)); crops.append((crop,bx0,by0))
# ---------- one screenshot per face: front first, then back, side, three-quarter; coherent regions
fvis=vis[f].all(1); bonus=np.array(BONUS); need=np.array(NEED)
score=np.where(fvis&(facing>0.15),facing,0)+np.where(fvis&(facing>need),bonus,0)
vs=np.zeros((m,nv)); vc=np.zeros(m)
for k in range(3): np.add.at(vs,f[:,k],score); np.add.at(vc,f[:,k],1)
vs/=np.maximum(vc,1)[:,None]
for _ in range(8): vs=np.where(iso[:,None],vs,0.5*vs+0.5*np.asarray(Dinv@(A@vs)))
fs=vs[f].mean(1)*(score>0)
label=np.where(fs.max(1)>0,fs.argmax(1),-1)
print('faces textured',round((label>=0).mean(),3),end=' -> ')
# grow into small holes: an unlabelled face takes its neighbours' screenshot when it is (leniently) visible there
fvis2=vis2[f].all(1)&(facing>0.05)
for _ in range(GROW):
    votes=np.zeros((m,nv))
    for k in range(3):
        ok=label>=0; np.add.at(votes,(f[ok,k],label[ok]),1)
    fv=votes[f].sum(1)*fvis2; cand=(label<0)&(fv.max(1)>=3)
    label[cand]=fv[cand].argmax(1)
print(round((label>=0).mean(),3),'per view',[int((label==i).sum()) for i in range(nv)])
# ---------- colours for what no photo shows
seen=acc_w>1e-4; col=np.zeros((m,3)); col[seen]=acc_c[seen]/acc_w[seen][:,None]
feat=np.hstack([P,NR*2.5]); dist,idx=cKDTree(feat[seen]).query(feat[~seen],k=8); w=1/(dist+0.2)**2; w/=w.sum(1,keepdims=True)
col[~seen]=(col[seen][idx]*w[...,None]).sum(1)
hid=(~seen)[:,None]
for _ in range(6): col=np.where(hid&~iso[:,None],0.5*col+0.5*np.asarray(Dinv@(A@col)),col)
soft=seen.astype(float)
for _ in range(4): soft=np.where(iso,soft,np.asarray(Dinv@(A@soft)).ravel())
col=np.clip(col,0,1)
