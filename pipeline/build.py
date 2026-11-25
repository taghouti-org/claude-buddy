import numpy as np, json, struct, sys, io
from PIL import Image, ImageFilter
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix, diags
from lib import *
OUT=sys.argv[1]; CELL=float(sys.argv[2]); UP=int(sys.argv[3]) if len(sys.argv)>3 else 2
CX,CYF,ZG=55.08,35.75,5.3
IM='ref8/'
FACE_TOL=0.8; ARM_REACH=1.45; VETO=False; SWORD_R=5.0; LID_MAX=9.0
BONUS=[1.0,0.3,0.6,0.0,0.3]; NEED=[0.30,0.30,0.30,0.15,0.30]; TONE=[0,3,1,4,2]   # front, side, back, three-quarter, other side
d=np.load('colored.npz'); V,F,N=d['v'],d['f'],d['n']; c0=np.load('weld.npz')['v'].mean(0)
fits=np.load('mvfits8.npy',allow_pickle=True).item(); views=list(fits)
# ---------- decimate
HEAD_CELL=float(sys.argv[4]) if len(sys.argv)>4 else CELL; fine=V[:,2]>56.5
key=np.where(fine[:,None],np.floor(V/HEAD_CELL),np.floor(V/CELL)).astype(np.int64); key=np.hstack([key,fine[:,None].astype(np.int64)])
u,inv=np.unique(key,axis=0,return_inverse=True); inv=inv.ravel(); m=len(u)
cnt=np.bincount(inv,minlength=m)[:,None]
P=np.stack([np.bincount(inv,V[:,i],m) for i in range(3)],1)/cnt
f=inv[F]; f=f[(f[:,0]!=f[:,1])&(f[:,1]!=f[:,2])&(f[:,0]!=f[:,2])]
_,fi=np.unique(np.sort(f,1),axis=0,return_index=True); f=f[np.sort(fi)]
def derive():
    global NR,fn,A,deg,Dinv,iso,m
    m=len(P); NR=vnormals(P,f); fn=np.cross(P[f[:,1]]-P[f[:,0]],P[f[:,2]]-P[f[:,0]]); fn/=np.maximum(np.linalg.norm(fn,axis=1,keepdims=True),1e-12)
    e=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]); A=coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(m,m)).tocsr(); A=A+A.T; A.data[:]=1
    deg=np.asarray(A.sum(1)).ravel(); Dinv=diags(1/np.maximum(deg,1)); iso=deg==0
derive(); print('verts',m,'faces',len(f))
REGION=open('region9.py').read(); GROW=25; REGION_OLD=open('region.py').read(); SKEL=open('skel.py').read()
from scipy.sparse.csgraph import connected_components
NOEDGE=np.zeros(len(P),bool); FORCE=NOEDGE.copy()
fits_new=fits; IM='refs/'; fits=np.load('mvfits2.npy',allow_pickle=True).item(); views=list(fits)
exec(REGION_OLD); col_old=col.copy()
_keep=(IM,fits,views); IM='ref9/'; fits=fits_new; views=list(fits); exec(REGION); col_new0=col.copy(); col=col_old.copy(); IM,fits,views=_keep   # the sharper drawings, for fine boundaries
#                                        # first pass on the original screenshots: only to learn each vertex's colour
exec(SKEL)                                              # skeleton + per-bone distance scores `sc`
# ---------- parts: swords, arms (sleeve + fist) and scarf are cut free from what they are fused to
def isskin(c_):
    mx2=c_.max(1); mn2=c_.min(1); s2=(mx2-mn2)/np.maximum(mx2,1e-6); return (mx2>0.62)&(s2>0.05)&(s2<0.5)&(c_[:,0]>c_[:,2])
mx=col.max(1); mn=col.min(1); Vv=mx; Sat=(mx-mn)/np.maximum(mx,1e-6); dl=np.maximum(mx-mn,1e-6)
hue=np.where(mx==col[:,0],((col[:,1]-col[:,2])/dl)%6,np.where(mx==col[:,1],(col[:,2]-col[:,0])/dl+2,(col[:,0]-col[:,1])/dl+4))*60
warm=((hue>8)&(hue<42))&((Sat>0.40)|((Sat>0.10)&(Vv>0.70)))            # jacket brown or skin
sc_h=sc.copy(); sc_h[:,names.index('head')]=1e3; near=sc_h.argmin(1)
part=np.zeros(m,int); dsh={}
def smooth_mask(mask,iters,thr=0.5):
    x=mask.astype(float)
    for _ in range(iters): x=np.where(iso,x,0.5*x+0.5*np.asarray(Dinv@(A@x)).ravel())
    return x>thr
def component_with(cand,seed):
    idx=np.where(cand)[0]; nc,lab=connected_components(A[idx][:,idx],directed=False); good=np.unique(lab[seed[idx]])
    out=np.zeros(m,bool); out[idx[np.isin(lab,good)]]=True; return out
for side,lab_,sg in (('left',1,1),('right',2,-1)):
    iu,il,ih=[names.index(side+k) for k in ('UpperArm','LowerArm','Hand')]; jh=JP[ih]; mine=Q[:,0]*sg>0
    # the sword: everything along its own axis that is not hand skin or sleeve
    sel=(near==ih)&(np.linalg.norm(Q-jh,axis=1)>12)&mine
    for _ in range(3):
        c=Q[sel].mean(0); ax=np.linalg.svd(Q[sel]-c,full_matrices=False)[2][0]; ax=ax if ax@(c-jh)>0 else -ax
        t=(Q-c)@ax; perp=np.linalg.norm((Q-c)-np.outer(t,ax),axis=1); tj=(jh-c)@ax
        sel=(perp<6)&(t>tj+12)&(t<tj+75)&mine
    blade=(perp<7.5)&(t>tj+12)&(t<tj+75)&mine
    grip=(perp<SWORD_R)&(t>tj-9)&(t<=tj+12)&mine&~isskin(col_new0)&~(warm&(Sat>0.4))
    sw=component_with(smooth_mask(blade|grip,2)|blade,blade)
    part[sw&(part==0)]=3+lab_; print(side,'sword verts',int(sw.sum()),'grip/guard',int((sw&~blade).sum()))
    # the arm: sleeve and fist, hugging the arm bones, grown from the shoulder
    chain=np.isin(near,[iu,il,ih]); ds=np.linalg.norm(Q-JP[iu],axis=1); dsh[lab_]=ds
    close=sc_h[:,[iu,il,ih]].min(1)<ARM_REACH
    arm=component_with(smooth_mask(chain&close&(warm|isskin(col_new0)|(ds<8))&(part==0),3),chain&(ds<6))
    part[arm&(part==0)]=lab_; print(side,'arm verts',int(arm.sum()))
# crumbs that only hung on through an arm or a sword go with it
idx=np.where(part==0)[0]; nc,lab=connected_components(A[idx][:,idx],directed=False); cnts=np.bincount(lab)
for comp in np.where(cnts<1500)[0]:
    vv=idx[lab==comp]; nbrs=np.unique(A[vv].indices); pn=part[nbrs]; pn=pn[pn>0]
    if len(pn): part[vv]=np.bincount(pn).argmax()
print('parts',{k:int((part==k).sum()) for k in range(6)})
zabs=Q[:,2]
red=((hue<14)|(hue>345))&(Sat>0.5)&(Vv>0.25)&(zabs>44)&(zabs<70)&(part==0)
red=smooth_mask(red,2); idx=np.where(red)[0]; nc,lab=connected_components(A[idx][:,idx],directed=False); cnts=np.bincount(lab)
scarf=np.zeros(m,bool); scarf[idx[cnts[lab]>150]]=True; part[scarf&(part==0)]=3; print('scarf verts',int((part==3).sum()))
# split: every face goes wholly to one part; vertices of the other part are duplicated for it
fl=part[f]; mixed=(fl.min(1)!=fl.max(1))
for lab_ in (1,2):                                      # ...except around the shoulder, where arm and torso must stay joined
    armbody=mixed&np.isin(fl,[0,lab_]).all(1)&(dsh[lab_][f]<10).all(1); mixed&=~armbody
maj=np.where((fl[:,0]==fl[:,1])|(fl[:,0]==fl[:,2]),fl[:,0],fl[:,1])
fm=np.where(mixed)[0]; corners=[]
for k in range(3):
    need=fl[fm,k]!=maj[fm]; corners.append(np.stack([fm[need],np.full(need.sum(),k),f[fm[need],k],maj[fm[need]]],1))
corners=np.concatenate(corners); pairs,pinv=np.unique(corners[:,2:],axis=0,return_inverse=True); pinv=pinv.ravel()
old_edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),1); ok_,oc=np.unique(old_edges[:,0]*10**7+old_edges[:,1],return_counts=True); old_open=ok_[oc==1]
orig=np.concatenate([np.arange(m),pairs[:,0]]); f=f.copy(); f[corners[:,0],corners[:,1]]=m+pinv
P=np.concatenate([P,P[pairs[:,0]]]); part=np.concatenate([part,pairs[:,1]]); print('duplicated verts',len(pairs),'in',int(mixed.sum()),'faces')
# close every rim the split opened, one loop and one part at a time, with a flat lid (no texture, colour of its rim)
de=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]); ks=np.minimum(de[:,0],de[:,1])*10**7+np.maximum(de[:,0],de[:,1])
uk,ui,uc=np.unique(ks,return_index=True,return_counts=True); be=de[ui[uc==1]]
ko=np.minimum(orig[be[:,0]],orig[be[:,1]])*10**7+np.maximum(orig[be[:,0]],orig[be[:,1]]); be=be[~np.isin(ko,old_open)]
be=be[part[be[:,0]]==part[be[:,1]]]                     # a lid never bridges two parts
n2=len(P); g2=coo_matrix((np.ones(len(be)),(be[:,0],be[:,1])),shape=(n2,n2)); nc,lab=connected_components(g2,directed=False)
el=lab[be[:,0]]; newP=[]; newpart=[]; capf=[]; lids=[]; nface0=len(f)
order_=np.argsort(el,kind='stable'); be=be[order_]; el=el[order_]; cuts=np.r_[0,np.where(np.diff(el))[0]+1,len(el)]
for a_,b_ in zip(cuts[:-1],cuts[1:]):
    ee=be[a_:b_]
    if len(ee)<4: continue
    rim=np.unique(ee); cen_=P[rim].mean(0); ext=np.linalg.norm(P[rim]-cen_,axis=1).max()
    if ext>LID_MAX: continue                            # a seam too long to lid sensibly: leave it open rather than make a sail
    newP.append(cen_); newpart.append(part[ee[0,0]]); ci=n2+len(newP)-1; lids.append((ci,rim))
    capf.append(np.stack([ee[:,1],ee[:,0],np.full(len(ee),ci)],1))
P=np.concatenate([P,np.array(newP)]); part=np.concatenate([part,np.array(newpart)]); f=np.concatenate([f]+capf); is_lid=np.arange(len(f))>=nface0
print('rims lidded',len(newP),'lid faces',int(is_lid.sum()))
IM='ref9/'; fits=fits_new; views=list(fits)
derive(); NOEDGE=np.zeros(len(P),bool); FORCE=NOEDGE.copy(); exec(REGION)                                  # second pass on the separated mesh, textured from the registered references
exec(SKEL)                                              # bone-relative coordinates for the separated mesh
_sc=sc.copy(); _sc[:,names.index('head')]=1e3; _near=_sc.argmin(1)
def near_h(i): return _near==i
def isskin(c_):
    mx2=c_.max(1); mn2=c_.min(1); s2=(mx2-mn2)/np.maximum(mx2,1e-6); return (mx2>0.62)&(s2>0.05)&(s2<0.5)&(c_[:,0]>c_[:,2])
col_old2=np.vstack([col_old[orig],np.tile([0.5,0.5,0.5],(m-len(orig),1))]); old_skin=isskin(col_old2)&(col_old2.max(1)>0.72)   # the original screenshots fit the sculpt exactly
# ---------- hair: everything dark on the head that stands off the face (eyes and brows lie ON the face and stay painted)
mx_=col.max(1); mn_=col.min(1); sat_=(mx_-mn_)/np.maximum(mx_,1e-6)
skin=(part==0)&(Q[:,2]>64)&(Q[:,2]<95)&(mx_>0.75)&(sat_>0.08)&(sat_<0.5)&(col[:,0]>col[:,2])&(NR[:,1]<-0.3)
Sx=Q[skin]; Amat=np.hstack([2*Sx,np.ones((len(Sx),1))]); sol=np.linalg.lstsq(Amat,(Sx**2).sum(1),rcond=None)[0]; cen=sol[:3]; rad_=np.sqrt(sol[3]+cen@cen)
dist=np.linalg.norm(Q-cen,axis=1)-rad_; res=dist[skin]; print('face sphere r',round(rad_,1),'centre',cen.round(1),'skin residual pct',np.percentile(res,[5,50,95]).round(2),'n',int(skin.sum()))
facezone=(NR[:,1]<-0.2)&(np.abs(Q[:,0]-cen[0])<23)&(Q[:,2]>67)&(Q[:,2]<92)&(dist<FACE_TOL)
hairv=(part==0)&(Q[:,2]>57.5)&((mx_<0.24)|((sat_<0.2)&(mx_<0.8))|(col_old2.max(1)<0.3))&~facezone   # dark in the drawings or in the originals (lock side walls)      # black, or a grey painted highlight
x=hairv.astype(float)
for _ in range(2): x=np.where(iso,x,0.5*x+0.5*np.asarray(Dinv@(A@x)).ravel())
hairv=(x>0.5)&~facezone&~old_skin                      # never where the original clearly shows skin
headz=(part==0)&(Q[:,2]>57.5)&~facezone&~old_skin
for _ in range(4):                                      # close pits: a head vertex ringed by hair is hair
    frac=np.asarray(Dinv@(A@hairv.astype(float))).ravel(); hairv|=headz&(frac>=0.6)
idx_=np.where(hairv)[0]; nc_,lab_h=connected_components(A[idx_][:,idx_],directed=False); big=np.bincount(lab_h).argmax(); hairv[:]=False; hairv[idx_[lab_h==big]]=True
print('hair verts',int(hairv.sum()))
NRh=NR.copy()                                           # silkier highlights: relax the hair normals
for _ in range(5):
    sm_=0.5*NRh+0.5*np.asarray(Dinv@(A@NRh)); sm_/=np.maximum(np.linalg.norm(sm_,axis=1,keepdims=True),1e-9); NRh=np.where((hairv&~iso)[:,None],sm_,NRh)
# the painted face keeps every front-view pixel, right up to the fringe (hair itself no longer needs texture)
NOEDGE=(part==0)&(Q[:,2]>63)&(Q[:,2]<96)&~hairv; hair_keep=hairv.copy(); NRh_keep=NRh
FORCE=NOEDGE&(NR[:,1]<-0.5)&(np.abs(Q[:,0]-cen[0])<19.5)&(Q[:,2]>66)&(Q[:,2]<93)
exec(REGION)
hairv=hair_keep
# ---------- keep the skin clean: off the painted face, head skin may only be skin-coloured
def isskin(c_):
    mx2=c_.max(1); mn2=c_.min(1); s2=(mx2-mn2)/np.maximum(mx2,1e-6); return (mx2>0.62)&(s2>0.05)&(s2<0.5)&(c_[:,0]>c_[:,2])
zone=(part==0)&(Q[:,2]>63)&(Q[:,2]<96)&~hairv
trusted=zone&(NR[:,1]<-0.5)&(np.abs(Q[:,0]-cen[0])<19.5)&(Q[:,2]>66)&(Q[:,2]<93)
suspect=zone&~trusted; skin_med=np.median(col[trusted&isskin(col)],axis=0); print('skin tone',skin_med.round(3),'suspect verts',int(suspect.sum()))
drop=np.zeros(len(f),bool)
for vi in range(nv):
    fv_=f[label==vi]; bad_f=suspect[fv_].all(1)&(~isskin(cvs[vi]))[fv_].any(1); idx_=np.where(label==vi)[0][bad_f]; drop[idx_]=True
drop|=suspect[f].all(1)                               # the sides of the face, the ears and under the chin: one clean skin tone
label[drop]=-1; fixv=np.zeros(m,bool); fixv[np.unique(f[drop])]=True; fixv&=suspect
col[fixv]=skin_med; print('skin faces repainted',int(drop.sum()))
# the original screenshots match the sculpt exactly: where they say "skin" and a drawing says "black", the drawing is off by a hair
# the front of the face is painted from the front drawing only: side drawings smear across it
tf=trusted[f].all(1)&(label>0); canfront=vis2[f][:,:,0].all(1)&(facing[:,0]>0.05)
label[tf&canfront]=0; label[tf&~canfront]=-1; print('face faces moved to the front view',int((tf&canfront).sum()),'to plain skin',int((tf&~canfront).sum()))
tv=np.zeros(m,bool); tv[np.unique(f[tf&~canfront])]=True; col[tv&trusted&~isskin(col)]=skin_med*0.95
nape=(part==0)&(Q[:,2]>60.5)&(Q[:,2]<69)&(Q[:,1]>3)&~hairv&isskin(col); col[nape]=[0.05,0.05,0.06]; label[nape[f].all(1)]=-1
shadow=np.percentile(col[trusted&isskin(col)],10,axis=0); print('under-fringe shadow tone',shadow.round(3))
col_old2=np.vstack([col_old[orig],np.tile([0.5,0.5,0.5],(m-len(orig),1))]); old_skin=isskin(col_old2)&(col_old2.max(1)>0.72); nveto=0
side_=np.abs(Q[:,0]-cen[0])>17                          # beyond the eyes: the drawing's side locks must not print on the temples
for vi in range(nv):
    veto=NOEDGE&old_skin&(cvs[vi].max(1)<0.42)&side_; fi_=np.where(label==vi)[0]; bad_f=veto[f[fi_]].any(1); label[fi_[bad_f]]=-1; nveto+=int(bad_f.sum())
    vv=np.zeros(m,bool); vv[np.unique(f[fi_[bad_f]])]=True; col[vv&old_skin]=skin_med*0.97
fixd=NOEDGE&old_skin&(col.max(1)<0.42)&side_; col[fixd]=skin_med*0.97; print('hair-on-skin faces vetoed',nveto)
# ---------- lids are flat-coloured from their rims, never textured
label[is_lid]=-1
for ci,rim in lids: col[ci]=col[rim].mean(0)
# ---------- atlas
gap=8; offs=[]; rows=[list(range(k,min(k+3,len(crops)))) for k in range(0,len(crops),3)]
AW=max(sum(crops[i][0].width+gap for i in row) for row in rows)+gap; AH=sum(max(crops[i][0].height for i in row)+gap for row in rows)+gap+24
atlas=Image.new('RGB',(AW,AH),(255,255,255)); oy=gap; offs=[None]*len(crops)
for row in rows:
    ox=gap
    for i in row:
        crop,bx0,by0=crops[i]; atlas.paste(crop,(ox,oy)); offs[i]=(ox,oy,bx0,by0); ox+=crop.width+gap
    oy+=max(crops[i][0].height for i in row)+gap
white=((AW-8)/AW,(AH-8)/AH)
buf=io.BytesIO(); atlas.save(buf,'PNG',optimize=True); png=buf.getvalue(); atlas.save('atlas.png'); print('atlas',atlas.size,round(len(png)/1e6,2),'MB')
# ---------- split vertices per (vertex, view)
corner_v=f.reshape(-1); corner_l=np.repeat(label,3)
pairs,cinv=np.unique(np.stack([corner_v,corner_l+1],1),axis=0,return_inverse=True); cinv=cinv.ravel()
ov=pairs[:,0]; ol=pairs[:,1]-1; nf=cinv.reshape(-1,3); M=len(ov)
uv=np.zeros((M,2)); uv[:]=white
for vi in range(len(views)):
    sel=ol==vi; ox,oy,bx0,by0=offs[vi]
    uv[sel,0]=(ox+(pxy[ov[sel],vi,0]+0.5-bx0)*UP)/AW; uv[sel,1]=(oy+(pxy[ov[sel],vi,1]+0.5-by0)*UP)/AH
C=np.where((ol>=0)[:,None],1.0,col[ov])
print('final verts',M,'faces',len(nf))
# ---------- rig: every part only listens to its own bones
exec(SKEL)
names=names+['Scarf']; JP=np.vstack([JP,[0,1.5,60.0]]); PARENT['Scarf']='neck'; nb=len(names); ix=names.index
scx=np.full((m,nb),1e3); scx[:,:nb-1]=sc; allowed=np.ones((m,nb),bool); allowed[:,ix('Scarf')]=False; allowed[:,ix('head')]=False
lower=[ix(k) for k in ('leftLowerArm','leftHand','rightLowerArm','rightHand')]
allowed[np.ix_(part==0,lower)]=False
for lab_,side in ((1,'left'),(2,'right')):
    only=np.zeros(nb,bool); only[[ix('chest'),ix(side+'UpperArm'),ix(side+'LowerArm'),ix(side+'Hand')]]=True; allowed[part==lab_]=only
wt=np.where(allowed,1/np.maximum(scx,0.05)**6,0); o4=np.argsort(-wt,1)[:,:4]; w=np.take_along_axis(wt,o4,1); w/=np.maximum(w.sum(1,keepdims=True),1e-12)
Wt=np.zeros_like(wt); np.put_along_axis(Wt,o4,w,1)
hh=np.clip((Q[:,2]-59.5)/4.0,0,1); hh=np.where(part==0,hh*hh*(3-2*hh),0); Wt*=(1-hh)[:,None]; Wt[:,ix('head')]+=hh
sf=part==3; Wt[sf]=0; Wt[sf,ix('Scarf')]=1
for pl_,side in ((4,'left'),(5,'right')): Wt[part==pl_]=0; Wt[part==pl_,ix(side+'Hand')]=1
W0=Wt.copy(); fixed=iso|sf|(part>=4)
for _ in range(10): Wt=np.where(fixed[:,None],Wt,0.5*Wt+0.5*np.asarray(Dinv@(A@Wt)))
Wt[fixed]=W0[fixed]; Wt=np.where(Wt.sum(1,keepdims=True)>1e-9,Wt,W0)
o4=np.argsort(-Wt,1)[:,:4]; w4=np.take_along_axis(Wt,o4,1); w4/=w4.sum(1,keepdims=True); w4[w4<0.02]=0; w4/=w4.sum(1,keepdims=True)
order,w4=o4[ov],w4[ov]
PV=P[ov].copy(); NV=np.where(hairv[ov][:,None],NRh_keep[ov],NR[ov])
# ---------- split the two blades off as their own meshes (so they can be put down), cap the cuts
Qs=PV-np.array([CX,CYF,0]); steel=np.array([0.40,0.40,0.43]); BIG=10**7
def ekeys(F_):
    e=np.concatenate([F_[:,[0,1]],F_[:,[1,2]],F_[:,[2,0]]]); a,b=ov[e[:,0]],ov[e[:,1]]
    return e,np.minimum(a,b)*BIG+np.maximum(a,b)
is_blade=np.zeros(len(nf),bool); bfaces={}; binfo={}
for side,pl_ in (('left',4),('right',5)):
    bf=(part[ov][nf]==pl_).all(1); bfaces[side]=bf; is_blade|=bf
    sv=Qs[part[ov]==pl_]; c=sv.mean(0); ax=np.linalg.svd(sv-c,full_matrices=False)[2][0]; ax=ax if ax@(c-JP[names.index(side+'Hand')])>0 else -ax
    binfo[side]=(c,ax,float(np.ptp((sv-c)@ax))); print(side,'sword faces',int(bf.sum()),'length mm',round(binfo[side][2],1))
add_P=[];add_N=[];add_uv=[];add_C=[];add_o=[];add_w=[]
is_hair=hairv[ov][nf].any(1)&~is_blade                    # lock side walls are hair too, never painted skin
tri={'body':[nf[~is_blade&~is_hair]],'hair':[nf[is_hair]],'left':[nf[bfaces['left']]],'right':[nf[bfaces['right']]]}; print('hair faces',int(is_hair.sum()))
PV=np.concatenate([PV]+add_P); NV=np.concatenate([NV]+add_N); uv=np.concatenate([uv]+add_uv); C=np.concatenate([C]+add_C)
order=np.concatenate([order]+add_o); w4=np.concatenate([w4]+add_w); M=len(PV); tri={k:np.concatenate(v) for k,v in tri.items()}
np.savez('rig10.npz',hair=np.concatenate([hairv[ov],np.zeros(len(PV)-len(ov),bool)]),nbody=len(tri['body']),nhair=len(tri['hair']),part=np.concatenate([part[ov],np.zeros(len(PV)-len(ov),int)]),P=PV,C=C,f=np.concatenate(list(tri.values())),NR=NV,order=order,w4=w4,JP=JP,names=np.array(names),uv=uv)
# ---------- glTF / VRM
K=1.0/(116.02-ZG)
def g(pts,rel=False):
    pts=np.asarray(pts,float); x=pts[...,0]-(0 if rel else CX); y=pts[...,1]-(0 if rel else CYF); z=pts[...,2]-ZG
    return np.stack([x*K,z*K,-y*K],-1)
pos=g(PV).astype('<f4'); nor=np.stack([NV[:,0],NV[:,2],-NV[:,1]],1).astype('<f4')
lin=np.where(C<=0.04045,C/12.92,((C+0.055)/1.055)**2.4); colr=np.hstack([np.round(lin*255),np.full((M,1),255)]).astype('u1')
jw=g(JP,rel=True); bufs=[];bviews=[];acc=[]
def addraw(b,target=None):
    off=sum(len(x) for x in bufs); bufs.append(b+b'\0'*((4-len(b)%4)%4)); v={'buffer':0,'byteOffset':off,'byteLength':len(b)}
    if target: v['target']=target
    bviews.append(v); return len(bviews)-1
def add(arr,type_,comp,target=None,norm=False,minmax=False):
    a={'bufferView':addraw(arr.tobytes(),target),'componentType':comp,'count':len(arr),'type':type_}
    if norm: a['normalized']=True
    if minmax: a['min']=arr.min(0).tolist(); a['max']=arr.max(0).tolist()
    acc.append(a); return len(acc)-1
a_pos=add(pos,'VEC3',5126,34962,minmax=True); a_nor=add(nor,'VEC3',5126,34962); a_uv=add(uv.astype('<f4'),'VEC2',5126,34962)
a_col=add(colr,'VEC4',5121,34962,norm=True); a_j=add(order.astype('<u2'),'VEC4',5123,34962); a_w=add(w4.astype('<f4'),'VEC4',5126,34962)
a_i={k:add(v.astype('<u4').reshape(-1),'SCALAR',5125,34963) for k,v in tri.items()}
ibm=np.tile(np.eye(4,dtype='<f4'),(len(names),1,1)); ibm[:,3,:3]=-jw; a_ibm=add(ibm.reshape(-1,16),'MAT4',5126)
bv_img=addraw(png)
nodes=[{'name':'Root','children':[1+names.index('hips')]}]
for i,k in enumerate(names):
    par=PARENT[k]; t=jw[i]-(jw[names.index(par)] if par else 0); nd={'name':k,'translation':[float(x) for x in t]}
    ch=[1+names.index(c) for c in names if PARENT[c]==k]
    if ch: nd['children']=ch
    nodes.append(nd)
mesh_nodes=[]
for mi,(k,nm) in enumerate((('body','Body'),('left','BladeL'),('right','BladeR'),('hair','Hair'))):
    nd={'name':nm,'mesh':mi,'skin':0}
    if k in binfo:
        c,ax,ln=binfo[k]; nd['extras']={'centre':[float(x) for x in g(c,rel=True)],'axis':[float(ax[0]),float(ax[2]),float(-ax[1])],'length':ln*K}
    nodes.append(nd); mesh_nodes.append(len(nodes)-1)
gltf={'asset':{'version':'2.0','generator':'claude-buddy stl2vrm'},'extensionsUsed':['VRMC_vrm','KHR_materials_unlit'],
 'scene':0,'scenes':[{'nodes':[0]+mesh_nodes}],'nodes':nodes,
 'meshes':[{'name':nm,'primitives':[{'attributes':({'POSITION':a_pos,'NORMAL':a_nor,'JOINTS_0':a_j,'WEIGHTS_0':a_w} if k=='hair' else {'POSITION':a_pos,'NORMAL':a_nor,'TEXCOORD_0':a_uv,'COLOR_0':a_col,'JOINTS_0':a_j,'WEIGHTS_0':a_w}),'indices':a_i[k],'material':1 if k=='hair' else 0,'mode':4}]} for k,nm in (('body','Body'),('left','BladeL'),('right','BladeR'),('hair','Hair'))],
 'images':[{'bufferView':bv_img,'mimeType':'image/png','name':'atlas'}],'samplers':[{'magFilter':9729,'minFilter':9987,'wrapS':33071,'wrapT':33071}],
 'textures':[{'source':0,'sampler':0}],
 'materials':[{'name':'Baked','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1],'baseColorTexture':{'index':0},'metallicFactor':0,'roughnessFactor':1},'extensions':{'KHR_materials_unlit':{}}},{'name':'Hair','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[0.012,0.012,0.018,1],'metallicFactor':0,'roughnessFactor':0.42}}],
 'skins':[{'joints':[1+i for i in range(len(names))],'skeleton':1+names.index('hips'),'inverseBindMatrices':a_ibm}],
 'accessors':acc,'bufferViews':bviews,'buffers':[{'byteLength':sum(len(x) for x in bufs)}],
 'extensions':{'VRMC_vrm':{'specVersion':'1.0',
   'meta':{'name':'Chibi figure (from STL)','version':'1.9','authors':['converted from STL'],'licenseUrl':'https://vrm.dev/licenses/1.0/','avatarPermission':'onlyAuthor','commercialUsage':'personalNonProfit','allowExcessivelyViolentUsage':False,'allowExcessivelySexualUsage':False,'allowPoliticalOrReligiousUsage':False,'allowAntisocialOrHateUsage':False,'creditNotation':'required','allowRedistribution':False,'modification':'prohibited'},
   'humanoid':{'humanBones':{k:{'node':1+i} for i,k in enumerate(names) if k!='Scarf'}},
   'lookAt':{'type':'bone','offsetFromHeadBone':[0,float(16*K),float(20*K)]}}}}
js=json.dumps(gltf,separators=(',',':')).encode(); js+=b' '*((4-len(js)%4)%4); bin_=b''.join(bufs)
with open(OUT,'wb') as fh:
    fh.write(struct.pack('<4sII',b'glTF',2,28+len(js)+len(bin_))); fh.write(struct.pack('<I4s',len(js),b'JSON')); fh.write(js); fh.write(struct.pack('<I4s',len(bin_),b'BIN\0')); fh.write(bin_)
print('wrote',OUT,round((28+len(js)+len(bin_))/1e6,2),'MB')
