"""Rejected diagnostic ROI union experiment; does not publish model predictions."""
import sys,json,hashlib,time
from pathlib import Path
import cv2,numpy as np
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'scripts'))
from rtmlib import ViTPose
from rtmpose_adapter import normalize_coco,evaluate
out=root/'data/pose-vitpose-crop-probe-v1';out.mkdir(exist_ok=True)
demo=json.loads((root/'data/axel-demo-v1/data.json').read_text())
model=ViTPose('https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/coco/vitpose-b-coco.onnx',model_input_size=(192,256),backend='onnxruntime',device='cpu')
refs=[]
for v in ('v1','v2'):refs+=json.loads((root/f'data/pose-joint-review-{v}/user-annotations.json').read_text())['frames']
pred={k:{} for k in ('ViTPose-B','ViTPose-ROI')}
for clip in demo['clips']:
 base=json.loads((root/'data/pose-vitpose-pilot-v1'/f"{clip['id']}.json").read_text())
 raws=json.loads((root/'data/pose-vitpose-pilot-v1'/f"{clip['id']}.raw.json").read_text());rows=[];details=[]
 for i,(f,r) in enumerate(zip(clip['frames'],raws)):
  image_path=root/'work/step6-pose'/clip['id']/f"{f['frameIndex']:06d}.png"
  assert hashlib.sha256(image_path.read_bytes()).hexdigest()==f['originalFrameSha256']
  boxes=np.array([n['selectedBox'] for n in raws[max(0,i-1):i+2]])
  box=[float(boxes[:,0].min()),float(boxes[:,1].min()),float(boxes[:,2].max()),float(boxes[:,3].max())]
  im=cv2.cvtColor(cv2.imread(str(image_path)),cv2.COLOR_BGR2RGB)
  kp,sc=model(im,bboxes=[box]);lm=normalize_coco(kp[0],sc[0],1280,720,score_kind='heatmap_peak')
  rows.append(dict(frameIndex=f['frameIndex'],time=f['time'],landmarks=lm))
  details.append(dict(frameIndex=f['frameIndex'],selectedBox=box,keypointsPixels=kp[0].tolist(),scores=sc[0].tolist(),sourceFrameSha256=f['originalFrameSha256']))
  pred['ViTPose-B'][clip['id'],f['frameIndex']]=f['pose']['ViTPose-B'];pred['ViTPose-ROI'][clip['id'],f['frameIndex']]=lm
  if i%25==0:print(clip['id'],f['frameIndex'],flush=True)
 (out/f"{clip['id']}.json").write_text(json.dumps({**base,'frames':rows,'model':{**base['model'],'name':'ViTPose-B ROI union radius1'}}))
 (out/f"{clip['id']}.raw.json").write_text(json.dumps(details))
e=evaluate(refs,pred);e['method']='Offline diagnostic union of previous/current/next detector boxes; same fixed pose model; no pose blending or side relabeling.'
(out/'evaluation.json').write_text(json.dumps(e,indent=2));print(json.dumps(e['models'],indent=2),flush=True)
