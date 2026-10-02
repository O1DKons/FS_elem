"""Re-estimate from original images at 384x288 using RTMPose-X.
Reuse recorded YOLOX boxes to isolate the pose model change; no relabeling.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
from rtmpose_adapter import normalize_coco, evaluate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/pose-rtmpose-x-pilot-v1'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--anchors-only',action='store_true');parser.add_argument('--model',choices=['rtmpose-x','vitpose-b'],default='rtmpose-x');args=parser.parse_args()
    global OUT
    label='RTMPose-X' if args.model=='rtmpose-x' else 'ViTPose-B'
    OUT=ROOT/('data/pose-rtmpose-x-pilot-v1' if args.model=='rtmpose-x' else 'data/pose-vitpose-pilot-v1')
    import cv2
    from rtmlib import RTMPose, ViTPose, Body
    OUT.mkdir(exist_ok=True)
    refs=[]
    for v in ('v1','v2'):refs+=json.loads((ROOT/f'data/pose-joint-review-{v}/user-annotations.json').read_text())['frames']
    anchors={(f['id'],f['frameIndex']) for f in refs}
    flagged={('competition-47-03-01',n) for n in (3629,3630,3631,3637,3650,3651,3652,3697)}|{('competition-20-01-01',n) for n in (1726,1736,1738,1741,1765)}|{('competition-44-01-01',1410)}
    demo=json.loads((ROOT/'data/axel-demo-v1/data.json').read_text())
    config=Body.MODE['performance'] if args.model=='rtmpose-x' else dict(pose='https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/coco/vitpose-b-coco.onnx',pose_input_size=(192,256))
    start=time.perf_counter()
    model_class=RTMPose if args.model=='rtmpose-x' else ViTPose
    model=model_class(config['pose'],model_input_size=config['pose_input_size'],to_openpose=False,backend='onnxruntime',device='cpu')
    provenance=dict(name=label+' (cached YOLOX-m boxes)',version='rtmlib-'+importlib.metadata.version('rtmlib'),weightsSha256=sha(Path(model.onnx_model)))
    settings=dict(model=provenance,url=config['pose'],inputSize=config['pose_input_size'],coordinatePolicy='Raw model outputs; no side exchange, smoothing, merging or manual corrections',device='cpu',backend='onnxruntime',boxSource='Recorded RTMPose-m pilot YOLOX-m selectedBox; no changes',sourceHashes={})
    settings['scorePolicy']='Heatmap peak clipped to [0,1] for schema; raw scores retained; not calibrated probability' if args.model=='vitpose-b' else 'Native bounded score'
    settings['colorInput']='BGR' if args.model=='rtmpose-x' else 'RGB'
    predictions={key:{} for key in ('Lite','Full','RTMPose',label)};times=[]
    for clip in demo['clips']:
        cache=ROOT/'data/pose-rtmpose-pilot-v1'/f"{clip['id']}.raw.json"
        settings['sourceHashes'][str(cache.relative_to(ROOT))]=sha(cache)
        cached={f['frameIndex']:f for f in json.loads(cache.read_text())}
        base=json.loads((ROOT/'data/pose-rtmpose-pilot-v1'/f"{clip['id']}.json").read_text())
        frames=[];raw=[]
        for f in clip['frames']:
            n=f['frameIndex']
            if args.anchors_only and (clip['id'],n) not in anchors|flagged:continue
            image_path=ROOT/'work/step6-pose'/clip['id']/f'{n:06d}.png'
            checksum=sha(image_path)
            if checksum!=f['originalFrameSha256'] or checksum!=cached[n]['sourceFrameSha256']:raise ValueError('Source image binding mismatch')
            im=cv2.imread(str(image_path))
            if im is None or im.shape[:2]!=(demo['height'],demo['width']):raise ValueError('Invalid source image')
            box=cached[n]['selectedBox'];points=[];scores=[];landmarks=[];tick=time.perf_counter()
            if box is not None:
                input_image=im if args.model=='rtmpose-x' else cv2.cvtColor(im,cv2.COLOR_BGR2RGB)
                kp,sc=model(input_image,bboxes=[box]);points=kp[0].tolist();scores=sc[0].tolist()
                landmarks=normalize_coco(points,scores,demo['width'],demo['height'],score_kind='heatmap_peak' if args.model=='vitpose-b' else 'bounded')
            ms=(time.perf_counter()-tick)*1000;times.append(ms)
            frames.append(dict(frameIndex=n,time=f['time'],landmarks=landmarks))
            raw.append(dict(frameIndex=n,sourceFrameSha256=checksum,selectedBox=box,keypointsPixels=points,scores=scores,inferenceMs=ms))
            for key in predictions:predictions[key][clip['id'],n]=landmarks if key==label else f['pose'][key]
            if args.anchors_only or len(frames)%25==0:print(clip['id'],n,round(ms),'ms',flush=True)
        proposal={k:base[k] for k in ('schemaVersion','kind','status','videoId','sourceSha256','coordinateSpace')};proposal.update(model=provenance,frames=frames)
        suffix='.anchors' if args.anchors_only else ''
        (OUT/f"{clip['id']}{suffix}.json").write_text(json.dumps(proposal,allow_nan=False))
        (OUT/f"{clip['id']}{suffix}.raw.json").write_text(json.dumps(raw,allow_nan=False))
    result=evaluate(refs,predictions);result.update(settings=settings,processedFrames=len(times),poseInferenceMs=times,elapsedSeconds=time.perf_counter()-start,method='Diagnostic six user-annotated frames. Cached identical detection boxes; model input settings and pose weights are recorded separately. No manual patches, no side relabeling. Not an independent test set.')
    (OUT/('evaluation-anchors.json' if args.anchors_only else 'evaluation.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result['models'],indent=2),flush=True)

if __name__=='__main__':main()
