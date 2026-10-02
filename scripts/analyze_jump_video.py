"""Short video -> frozen type classifier -> reviewable local report.
Run in phase-env. Does not pretend type label measures actual underrotation.
"""
import argparse,json,subprocess,hashlib
from pathlib import Path
from jump_video_report import result_contract,render_report

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--input',required=True,type=Path)
 parser.add_argument('--backend',choices=['video','pose'],default='video')
 parser.add_argument('--model',required=True,type=Path)
 parser.add_argument('--output',required=True,type=Path)
 args=parser.parse_args()
 if not args.input.is_file():raise ValueError('Input video missing')
 if args.output.exists() and any(args.output.iterdir()):raise ValueError('Output must be new or empty')
 if args.backend=='pose':
  from video_pose_type import predict_clip
 else:
  from video_type_model import predict_clip
 prediction=predict_clip(args.input,args.model)
 result=result_contract(prediction)
 result['modelSha256']=hashlib.sha256(args.model.read_bytes()).hexdigest()
 import numpy as np
 with np.load(args.model,allow_pickle=False) as artifact:
  result['modelProvenance']={k:str(artifact[k]) for k in ('extractor','manifest_sha256','extractor_provenance') if k in artifact}
 args.output.mkdir(parents=True,exist_ok=True)
 try:
  import imageio_ffmpeg
  ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
 except ImportError:
  import shutil
  ffmpeg=shutil.which('ffmpeg')
  if not ffmpeg:raise RuntimeError('ffmpeg or imageio_ffmpeg required for report video')
 # Encode browser-compatible video; no shell interpolation and no source mutation.
 subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(args.input),'-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output/'sample.mp4')],check=True)
 (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 (args.output/'index.html').write_text(render_report(result,'sample.mp4'))
 print(json.dumps({'report':str((args.output/'index.html').resolve()),'elementProposal':result['elementProposal'],'rotationAssessment':None},ensure_ascii=False))
if __name__=='__main__':main()
