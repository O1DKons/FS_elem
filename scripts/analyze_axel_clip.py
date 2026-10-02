"""Experimental end-to-end short-clip plumbing. Not a validated automatic judging system."""
import argparse,hashlib,json,subprocess,html
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
POSE_PY=ROOT/'work/step23-rtmpose/venv/bin/python'

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--type-backend',choices=['video','fusion'],default='fusion');parser.add_argument('--input',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
 source=args.input.resolve();out=args.output.resolve()
 if out.exists() and any(out.iterdir()):raise ValueError('Use a new output directory')
 if not source.is_file():raise ValueError('Input video missing')
 import imageio_ffmpeg,math
 reader=imageio_ffmpeg.read_frames(str(source));metadata=next(reader);reader.close()
 duration=metadata.get('duration',0)
 if not math.isfinite(duration) or not 0<duration<=10.05:raise ValueError('Use a short single-element video up to10seconds')
 out.mkdir(parents=True,exist_ok=True)
 if args.type_backend=='fusion':
  from video_fusion_type import predict_clip
  type_model=ROOT/'work/video-fusion-type-v1/classifier.joblib'
  provenance=json.loads((ROOT/'work/video-fusion-type-v1/results.json').read_text())
 else:
  from video_type_model import predict_clip
  type_model=ROOT/'work/video-type-pilot-v1/classifier.npz'
  provenance=json.loads((ROOT/'work/video-type-pilot-v1/results.json').read_text())
 prediction=predict_clip(source,type_model)
 result=dict(schemaVersion=1,status='experimental_unvalidated_pipeline',reviewRequired=True,sourceSha256=prediction['video_sha256'],typeProposal=prediction,measuredRevolutions=None,underrotationDegrees=None,rotationAssessment=None,scope='Short single-element clip only. Not validated end-to-end; contact errors can change rotation classification. No claim of70% video accuracy.')
 result['typeSeenTrainingClip']=any(r['sha256']==prediction['video_sha256'] for r in provenance['records'])
 result['modelSha256']={'type':hashlib.sha256(type_model.read_bytes()).hexdigest()}
 if prediction['predicted_label'] in ('1A','2A','3A'):
  landmarks=out/'landmarks'
  subprocess.run([str(POSE_PY),str(ROOT/'scripts/infer_jump_landmarks.py'),'--video',str(source),'--output',str(landmarks)],check=True)
  from phase_contact_visual import predict_pose
  phase_model=ROOT/'work/phase-contact-rtmw/classifier.joblib'
  pose=json.loads((landmarks/'pose.json').read_text())
  contact=predict_pose(pose,landmarks,phase_model,use_duration_prior=prediction['predicted_label']=='2A')
  result['contactProposal']=contact
  first=contact['predictedFirstContact']
  if first is not None:
   subprocess.run([str(POSE_PY),str(ROOT/'scripts/infer_jump_landmarks.py'),'--output',str(landmarks),'--augment-contact',str(first/50)],check=True)
   from landing_rotation_model import predict_item
   binary_model=ROOT/'work/landing-rotation-model/classifier.npz';boot=json.loads((landmarks/'boot.json').read_text())
   with np.load(binary_model,allow_pickle=False) as model:
    proposal=predict_item(boot['items'][0],model,boot['fps']);result['rotationSeenTrainingSource']=prediction['video_sha256'] in model['trainingSourceSha256'].tolist()
   result['rotationProposal']=proposal
   # The binary training set supports reviewed double Axels only.
   if prediction['predicted_label']=='2A':result['rotationLimitation']='Automatic-contact rotation output withheld: held-out test fell to8/20. Contact confirmation required.'
   else:result['rotationLimitation']='Binary model trained on doubleAxels; output not applied to other rotation classes.'
   result['modelSha256'].update(contact=hashlib.sha256(phase_model.read_bytes()).hexdigest(),rotation=hashlib.sha256(binary_model.read_bytes()).hexdigest())
  else:result['reason']='Insufficient visible pose for a contact proposal.'
 else:result['reason']='Type model did not propose an Axel. This does not prove the video contains none.'
 import imageio_ffmpeg
 subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-nostdin','-i',str(source),'-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'sample.mp4')],check=True)
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 from axel_pipeline_report import render
 frame_rows=json.loads((out/'landmarks/pose.json').read_text())['frames'] if (out/'landmarks/pose.json').exists() else []
 page=render(result,frame_rows)
 (out/'index.html').write_text(page);print(json.dumps({'report':str(out/'index.html'),'type':prediction['predicted_label'],'rotationAssessment':result['rotationAssessment']},ensure_ascii=False))
if __name__=='__main__':main()
