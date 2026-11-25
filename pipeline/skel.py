# ---------- skeleton (mm, relative to CX / CYF / absolute z); character's left = +x, front = -y
J={ 'hips':(0,1.5,30),'spine':(0,1.5,37),'chest':(0,1.5,46),'neck':(0,1.5,58),'head':(0,1.5,64),
    'leftUpperArm':(12,2.5,56),'leftLowerArm':(19,5.5,46),'leftHand':(24,7.5,38),
    'rightUpperArm':(-12,2.5,56),'rightLowerArm':(-19,5.5,46),'rightHand':(-24,7.5,38),
    'leftUpperLeg':(7.5,0,29),'leftLowerLeg':(7.5,0,19),'leftFoot':(7.5,0,9),
    'rightUpperLeg':(-7.5,0,29),'rightLowerLeg':(-7.5,0,19),'rightFoot':(-7.5,0,9)}
PARENT={'hips':None,'spine':'hips','chest':'spine','neck':'chest','head':'neck',
    'leftUpperArm':'chest','leftLowerArm':'leftUpperArm','leftHand':'leftLowerArm',
    'rightUpperArm':'chest','rightLowerArm':'rightUpperArm','rightHand':'rightLowerArm',
    'leftUpperLeg':'hips','leftLowerLeg':'leftUpperLeg','leftFoot':'leftLowerLeg',
    'rightUpperLeg':'hips','rightLowerLeg':'rightUpperLeg','rightFoot':'rightLowerLeg'}
names=list(J); JP=np.array([J[k] for k in names],float)
END={'hips':'spine','spine':'chest','chest':'neck','neck':'head','leftUpperArm':'leftLowerArm','leftLowerArm':'leftHand',
     'rightUpperArm':'rightLowerArm','rightLowerArm':'rightHand','leftUpperLeg':'leftLowerLeg','leftLowerLeg':'leftFoot',
     'rightUpperLeg':'rightLowerLeg','rightLowerLeg':'rightFoot'}
TIP={'head':(0,1.5,110),'leftHand':(52,-35,18),'rightHand':(-52,-35,18),'leftFoot':(7.5,-6,5.5),'rightFoot':(-7.5,-6,5.5)}
RAD={'hips':14,'spine':13,'chest':12,'neck':8,'head':30,'UpperArm':5.5,'LowerArm':4.5,'Hand':4,'UpperLeg':8.5,'LowerLeg':7,'Foot':6}
def rad(k): return RAD.get(k) or RAD[k.replace('left','').replace('right','')]
Q=P-np.array([CX,CYF,0])
def segdist(q,a,b):
    ab=b-a; t=np.clip(((q-a)@ab)/(ab@ab),0,1); return np.linalg.norm(q-(a+t[:,None]*ab),axis=1)
sc=np.zeros((m,len(names)))
for i,k in enumerate(names):
    a=np.array(J[k],float); b=np.array(J[END[k]] if k in END else TIP[k],float)
    sc[:,i]=segdist(Q,a,b)/rad(k)
