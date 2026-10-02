"""Experimental scan over fixed windows, no manual jump timestamp needed."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from video_scan import windows,select_candidates

def window_encode_command(ffmpeg,source,start,end,destination):
 return [ffmpeg,'-v','error','-nostdin','-y','-ss',str(start),'-i',str(source),
         '-t',str(end-start),'-an','-vf','scale=171:128','-c:v','libx264rgb',
         '-preset','ultrafast','-pix_fmt','rgb24',str(destination)]

def scan(path,model):
 import imageio_ffmpeg
 from video_type_model import predict_clip
 source_hash=hashlib.sha256(Path(path).read_bytes()).hexdigest()
 reader=imageio_ffmpeg.read_frames(str(path));metadata=next(reader);reader.close()
 duration=metadata.get('duration',0)
 if duration>600:raise ValueError('Pilot scan limited to 10 minutes')
 results=[]
 with tempfile.TemporaryDirectory(prefix='fs-elem-scan-') as directory:
  clip=Path(directory)/'window.mp4'
  for start,end in windows(duration):
   subprocess.run(window_encode_command(imageio_ffmpeg.get_ffmpeg_exe(),path,start,end,clip),check=True)
   prediction=predict_clip(clip,model)
   results.append(dict(start=start,end=end,prediction=prediction))
 return dict(schemaVersion=1,sourceSha256=source_hash,modelSha256=hashlib.sha256(Path(model).read_bytes()).hexdigest(),duration=duration,candidates=select_candidates(results),windows=results,scope='Experimental fixed1.5s/0.5s scan. Candidate intervals only, not takeoff/landing. Raw classifier margin, not calibrated confidence. No validated full-program accuracy, underrotation or measured revolution count.')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--input',required=True,type=Path);parser.add_argument('--model',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
 if args.output.exists():raise ValueError('Use a new output path')
 result=scan(args.input,args.model);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));print(json.dumps(result['candidates'],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
