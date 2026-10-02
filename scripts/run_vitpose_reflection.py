"""Offline paired reflection experiment. Never chooses variants using references."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from rtmlib import ViTPose
from pose_reflection import restore_heatmaps
from rtmpose_adapter import normalize_coco,evaluate
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/pose-vitpose-reflection-v1'
def main():
    OUT.mkdir(exist_ok=True)
    demo=json.loads((ROOT/'data/axel-demo-v1/data.json').read_text())
    model=ViTPose('https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/coco/vitpose-b-coco.onnx',model_input_size=(192,256),backend='onnxruntime',device='cpu')
    refs=[]
    for version in ('v1','v2'):refs+=json.loads((ROOT/f'data/pose-joint-review-{version}/user-annotations.json').read_text())['frames']
    predictions={k:{} for k in ('ViTPose-B','ViTPose-reflected','ViTPose-TTA')}
    start=time.perf_counter()
    for clip in demo['clips']:
        base=json.loads((ROOT/'data/pose-vitpose-pilot-v1'/f"{clip['id']}.json").read_text())
        raws=json.loads((ROOT/'data/pose-vitpose-pilot-v1'/f"{clip['id']}.raw.json").read_text())
        assert [(f['frameIndex'],f['time']) for f in base['frames']]==[(f['frameIndex'],f['time']) for f in clip['frames']]
        outputs={k:[] for k in ('ViTPose-reflected','ViTPose-TTA')}; diagnostic=[]
        for i,(frame,raw) in enumerate(zip(clip['frames'],raws)):
            n=frame['frameIndex'];image_path=ROOT/'work/step6-pose'/clip['id']/f'{n:06d}.png'
            assert hashlib.sha256(image_path.read_bytes()).hexdigest()==frame['originalFrameSha256']==raw['sourceFrameSha256']
            image=cv2.cvtColor(cv2.imread(str(image_path)),cv2.COLOR_BGR2RGB)
            cropped,center,scale=model.preprocess(image,raw['selectedBox'])
            h0=model.inference(cropped)[0]
            h1=restore_heatmaps(model.inference(np.ascontiguousarray(cropped[:,::-1]))[0])
            diagnostic.append(dict(frameIndex=n,sourceFrameSha256=raw['sourceFrameSha256'],selectedBox=raw['selectedBox'],variants={}))
            predictions['ViTPose-B'][clip['id'],n]=frame['pose']['ViTPose-B']
            for name,heatmaps in [('ViTPose-reflected',h1),('ViTPose-TTA',(h0+h1)*.5)]:
                kp,scores=model.postprocess([heatmaps.copy()],center,scale)
                points=normalize_coco(kp[0],scores[0],1280,720,score_kind='heatmap_peak')
                outputs[name].append(dict(frameIndex=n,time=frame['time'],landmarks=points))
                predictions[name][clip['id'],n]=points
                diagnostic[-1]['variants'][name]=dict(keypointsPixels=kp[0].tolist(),scores=scores[0].tolist())
            if i%25==0: print(clip['id'],n,flush=True)
        for name,frames in outputs.items():
            proposal={**base,'frames':frames,'model':{**base['model'],'name':name+' ViTPose-B COCO'}}
            (OUT/f"{clip['id']}.{name}.json").write_text(json.dumps(proposal,allow_nan=False))
        (OUT/f"{clip['id']}.raw.json").write_text(json.dumps(diagnostic,allow_nan=False))
    report=evaluate(refs,predictions)
    report.update(elapsedSeconds=time.perf_counter()-start,method='Original crop and horizontally reflected input; reflected heatmaps restored with COCO anatomical permutation. TTA averages heatmaps BEFORE decoding. No temporal swaps or reference-based point selection. Six known diagnostic frames, not held-out validation.',weightsSha256=hashlib.sha256(Path(model.onnx_model).read_bytes()).hexdigest())
    (OUT/'evaluation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report['models'],indent=2),flush=True)
if __name__=='__main__':main()
