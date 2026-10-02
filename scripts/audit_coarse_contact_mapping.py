"""Reproduce contact-only pixel alignment; do not assert entire export mapping."""
import json,sqlite3,bisect
from pathlib import Path
import numpy as np
from video_type_model import ROOT,sha
from video_native_type import validated_native
OUTPUT=ROOT/'work/full-context-contact-v1'
def run(output=OUTPUT):
 import cv2
 manifest=ROOT/'data/step3-candidates/active-axels.json';contacts=ROOT/'data/axel-demo-v1/rotation-review-data.json'
 rows=json.loads(manifest.read_text())['items'];truth={r['attemptId']:r for r in json.loads(contacts.read_text())['items']}
 db=sqlite3.connect(f'file:{ROOT}/data/live/fs-elem.sqlite?mode=ro',uri=True);result=[]
 for r in rows:
  t=truth[r['id']];clip=ROOT/'data/step3-candidates'/r['clip'];assert sha(clip)==r['clipSha256'];assert t['sourceSha256']==r['sourceSha256FromCatalog']
  times=[x[0] for x in db.execute('SELECT seconds FROM frame_times WHERE video_id=? ORDER BY frame_index',(r['videoId'],))]
  bounds=[bisect.bisect_left(times,r['sourceStart']),bisect.bisect_left(times,r['sourceEnd'])-1];assert bounds==r['sourceFrameRange']
  points,scores,fps,indices,provenance,cache_sha=validated_native({'sha256':r['clipSha256']},ROOT/'phase-cache/video-pose-dense-challenge-v2')
  anchors=[]
  for name in ['lastContact','firstContact']:
   fr=t[name];meta=next(x for x in t['frames'] if x['frameIndex']==fr);png=ROOT/'data/axel-demo-v1'/meta['image'];assert sha(png)==meta['sourceFrameSha256']
   ref=cv2.resize(cv2.imread(str(png)),(320,180)).astype(float);cap=cv2.VideoCapture(str(clip));local=fr-bounds[0];errors=[]
   for offset in range(-2,3):
    cap.set(cv2.CAP_PROP_POS_FRAMES,local+offset);ok,image=cap.read();assert ok;errors.append(float(np.abs(cv2.resize(image,(320,180)).astype(float)-ref).mean()))
   cap.release();best=int(np.argmin(errors))-2;margin=sorted(errors)[1]-min(errors)
   if best!=0 or margin<.1:raise ValueError('Ambiguous/inconsistent contact anchor')
   anchors.append(dict(contact=name,sourceFrame=fr,localFrame=local,pngSha256=sha(png),offsets=[-2,-1,0,1,2],mae=errors,bestOffset=best,runnerUpMargin=margin))
  result.append(dict(attemptId=r['id'],sourceSha256=t['sourceSha256'],clipSha256=r['clipSha256'],sourceFrameRange=bounds,frames=len(points),fps=fps,nativeCacheSha256=cache_sha,nativeProvenance=provenance,anchors=anchors,finalFrameMappingUnverified=len(points)!=bounds[1]-bounds[0]+1))
 db.close();output.mkdir(parents=True,exist_ok=True)
 report=dict(schemaVersion=1,records=result,inputSha256={str(manifest):sha(manifest),str(contacts):sha(contacts),str(Path(__file__)):sha(__file__),str(ROOT/'work/step3/export_candidates.py'):sha(ROOT/'work/step3/export_candidates.py')},method='OpenCV decoded BGR resized320x180 INTER_LINEAR; mean absolute pixel error vs hash-verified original contact PNG; +/-2frames; winner mustoffset0 and margin>=0.1. Only contact anchors checked. Originalsourcevideos not rehashed; sourceSHA metadata compared.')
 (output/'mapping-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False));return report
if __name__=='__main__':run()
