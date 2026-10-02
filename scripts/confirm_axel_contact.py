"""Apply explicit UI confirmation to one analysis only; never relabel training data."""
import argparse,json,subprocess,hashlib
from pathlib import Path
import numpy as np
from landing_rotation_model import predict_item
from axel_pipeline_report import render
ROOT=Path(__file__).resolve().parents[1]
def contact_pose_bundle(out,result,frame):
 folder=out/result.get('landmarksDirectory','landmarks');pose=json.loads((folder/'pose.json').read_text())
 original=next((r for r in pose['frames'] if r['frameIndex']==frame),None)
 if original is None:raise ValueError('Unknown frame')
 if not pose.get('settings',{}).get('sourceReuse'):
  target=out/'landmarks-v2'
  if not (target/'pose.json').exists():
   subprocess.run([str(ROOT/'work/step23-rtmpose/venv/bin/python'),str(ROOT/'scripts/infer_jump_landmarks.py'),'--video',pose['sourcePath'],'--output',str(target)],check=True)
  updated=json.loads((target/'pose.json').read_text())
  selected=next((r for r in updated['frames'] if r['frameIndex']==frame),{})
  if updated['sourceSha256']!=pose['sourceSha256'] or any(selected.get(k)!=original.get(k) for k in ('sourceFrameIndex','sourceFrameSha256')):raise ValueError('Re-extracted contact no longer matches selected source frame')
  if not updated.get('settings',{}).get('sourceReuse'):raise ValueError('Re-extraction did not enable source reuse')
  folder,pose=target,updated
  result['landmarksDirectory']=target.name
 return folder,pose

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);parser.add_argument('--frame',required=True,type=int);args=parser.parse_args();out=args.output
 result=json.loads((out/'result.json').read_text());landmarks,pose=contact_pose_bundle(out,result,args.frame)
 if args.frame not in {r['frameIndex'] for r in pose['frames']}:raise ValueError('Unknown frame')
 if result['typeProposal']['predicted_label']!='2A':raise ValueError('Binary model supports2A only')
 target=landmarks/f'boot-confirmed-{args.frame}.json'
 if not target.exists():subprocess.run([str(ROOT/'work/step23-rtmpose/venv/bin/python'),str(ROOT/'scripts/infer_jump_landmarks.py'),'--output',str(landmarks),'--augment-contact',str(args.frame/50),'--boot-output',str(target)],check=True)
 boot=json.loads(target.read_text());model_path=ROOT/'work/landing-rotation-model/classifier.npz'
 if boot['poseSha256']!=hashlib.sha256((landmarks/'pose.json').read_bytes()).hexdigest():raise ValueError('Pose changed')
 if boot['items'][0]['firstContact']!=args.frame or boot['items'][0]['sourceSha256']!=pose['sourceSha256']:raise ValueError('Contact/source mismatch')
 with np.load(model_path,allow_pickle=False) as model:proposal=predict_item(boot['items'][0],model,boot['fps'])
 result.update(userConfirmedContactFrame=args.frame,contactSource='explicit_user_confirmation_for_this_analysis',rotationProposal=proposal,rotationAssessment=proposal['rotationAssessment'],reviewRequired=True)
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));(out/'index.html').write_text(render(result,pose['frames']))
if __name__=='__main__':main()
