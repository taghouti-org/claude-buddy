import numpy as np
from scipy import ndimage as ndi
def vnormals(v,f):
    fn=np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]])
    n=np.zeros_like(v)
    for i in range(3): np.add.at(n,f[:,i],fn)
    return n/np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
def rot(yaw,pitch):
    cy,sy,cp,sp=np.cos(yaw),np.sin(yaw),np.cos(pitch),np.sin(pitch)
    Rz=np.array([[cy,-sy,0],[sy,cy,0],[0,0,1]])          # spin model about its up axis (z)
    # camera basis: right=x, up=z tilted by pitch, depth=y
    Rx=np.array([[1,0,0],[0,cp,-sp],[0,sp,cp]])
    return Rx@Rz
def splat(v,n,yaw=0,pitch=0,scale=5.0,size=(700,700),center=None,col=None):
    """Orthographic vertex splat. Camera looks along +y (so shows the -y side). Returns rgb, depth, index image."""
    R=rot(yaw,pitch); c=v.mean(0) if center is None else center
    p=(v-c)@R.T; nn=n@R.T
    W,H=size
    x=np.round(p[:,0]*scale+W/2).astype(int); y=np.round(-p[:,2]*scale+H/2).astype(int); d=p[:,1]
    ok=(x>=0)&(x<W)&(y>=0)&(y<H)&(nn[:,1]<0.15)
    idx=np.where(ok)[0]; pix=y[idx]*W+x[idx]
    o=np.lexsort((d[idx],pix)); pix=pix[o]; idx=idx[o]
    first=np.r_[True,pix[1:]!=pix[:-1]]
    img_i=-np.ones(W*H,int); img_i[pix[first]]=idx[first]
    dep=np.full(W*H,np.inf); dep[pix[first]]=d[idx[first]]
    img_i=img_i.reshape(H,W); dep=dep.reshape(H,W)
    m=img_i>=0
    L=np.array([0.3,-0.8,0.5]); L/=np.linalg.norm(L)
    sh=np.clip(nn@L,0,1)*0.75+0.25
    rgb=np.zeros((H,W,3))
    base=np.ones((len(v),3))*0.8 if col is None else col
    rgb[m]=base[img_i[m]]*sh[img_i[m]][:,None]
    return (rgb*255).astype('uint8'),dep,img_i
def flat(v,n,col,yaw=0,scale=5.0,size=(600,620),center=None,grid=False):
    """Unlit vertex splat with small hole fill; optional mm grid (labels = model x/z)."""
    from PIL import Image, ImageDraw
    R=rot(yaw,0); c=v.mean(0) if center is None else center
    p=(v-c)@R.T; nn=n@R.T; W,H=size
    x=np.round(p[:,0]*scale+W/2).astype(int); y=np.round(-p[:,2]*scale+H/2).astype(int); d=p[:,1]
    ok=(x>=0)&(x<W)&(y>=0)&(y<H)&(nn[:,1]<0.2); idx=np.where(ok)[0]; pix=y[idx]*W+x[idx]
    o=np.lexsort((d[idx],pix)); pix=pix[o]; idx=idx[o]; first=np.r_[True,pix[1:]!=pix[:-1]]
    ii=-np.ones(W*H,int); ii[pix[first]]=idx[first]; ii=ii.reshape(H,W)
    m=ii>=0
    # fill pinholes with nearest filled pixel inside the closed silhouette
    sil=ndi.binary_closing(m,iterations=2)
    _,(iy,ix)=ndi.distance_transform_edt(~m,return_indices=True)
    ii2=ii[iy,ix]; rgb=np.full((H,W,3),0.22); rgb[sil]=col[ii2[sil]]
    im=Image.fromarray((np.clip(rgb,0,1)*255).astype('uint8'))
    if grid:
        dr=ImageDraw.Draw(im)
        for z in range(0,121,10):
            yy=int(-(z-c[2])*scale+H/2); dr.line([(0,yy),(W,yy)],fill=(90,90,90)); dr.text((2,yy-10),str(z),fill=(255,255,0))
        for gx in range(-60,61,10):
            xx=int(gx*scale+W/2); dr.line([(xx,0),(xx,H)],fill=(70,70,70)); dr.text((xx+2,2),str(gx),fill=(0,255,255))
    return im
def proj(V,c,prm):
    """Perspective camera: prm = yaw,pitch,scale,tx,ty,D (D = camera distance in mm from model centre)."""
    yaw,pitch,s,tx,ty,D=prm
    R=rot(yaw,pitch); p=(V-c)@R.T; k=s*D/(D+p[:,1])
    return p[:,0]*k+tx, -p[:,2]*k+ty, p[:,1], R
def proj(V,c,prm):
    """Perspective camera + optional row-wise warp.
    prm = [yaw,pitch,scale,tx,ty,D] (+ [y0,y1,warp]) where warp is K x 3 (dy, sx, dx) at K knots evenly spaced in image y between y0 and y1."""
    yaw,pitch,s,tx,ty,D=prm[:6]
    R=rot(yaw,pitch); p=(V-c)@R.T; k=s*D/(D+p[:,1]); x=p[:,0]*k+tx; y=-p[:,2]*k+ty
    if len(prm)>6:
        y0,y1,w=prm[6],prm[7],np.asarray(prm[8]); kn=np.linspace(y0,y1,len(w))
        dy=np.interp(y,kn,w[:,0]); sx=np.interp(y,kn,w[:,1]); dx=np.interp(y,kn,w[:,2])
        x=tx+(x-tx)*sx+dx; y=y+dy
    return x,y,p[:,1],R
