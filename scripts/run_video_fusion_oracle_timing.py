"""ORACLE TIMING diagnostic: manual flight windows, frozen fusion, no training."""
import json
import re
import subprocess
from pathlib import Path
import imageio_ffmpeg
from video_fusion_type import ROOT,TRUSTED_ARTIFACT,predict_clip
from video_type_model import sha
from video_pose_type import evaluate


def main():
    contacts_path=ROOT/'data/axel-demo-v1/rotation-review-data.json'
    labels_path=ROOT/'data/step3-candidates/active-axels.json'
    contacts=json.loads(contacts_path.read_text());labels={i['id']:i for i in json.loads(labels_path.read_text())['items']}
    assert contacts['fps']==50 and len(contacts['items'])==23
    output=ROOT/'work/video-fusion-oracle-timing';clips=output/'clips';clips.mkdir(parents=True,exist_ok=True)
    verified={};records=[];ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    for item in contacts['items']:
        attempt=item['attemptId'];metadata=labels[attempt]
        code=metadata.get('protocolElementCode',metadata.get('protocolCode','')).replace('А','A')
        match=re.match(r'^([123]A)',code)
        if not match:raise ValueError('Unknown nominal target')
        truth=match.group(1)
        start=item['lastContact']-12;end=item['firstContact']+12;expected=end-start+1
        source=ROOT/'data/live/media'/(item['videoId']+'.mp4');clip=clips/(attempt+'.mp4')
        command=[]
        try:
            if source not in verified:verified[source]=sha(source)
            if verified[source]!=item['sourceSha256'] or verified[source]!=metadata['sourceSha256FromCatalog']:
                raise ValueError('Original source SHA256 mismatch')
            reader=imageio_ffmpeg.read_frames(str(source));video_metadata=next(reader);reader.close()
            if abs(video_metadata['fps']-50)>.01:raise ValueError('Expected actual50fps source')
            if start<0 or expected<=0:raise ValueError('Invalid manual contact window')
            command=[ffmpeg,'-v','error','-y','-threads','2','-i',str(source),'-map','0:v:0','-an',
                     '-vf',f'select=between(n\\,{start}\\,{end}),setpts=N/(50*TB)',
                     '-frames:v',str(expected),'-r','50','-c:v','libx264','-threads','2',
                     '-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(clip)]
            subprocess.run(command,check=True,capture_output=True,text=True,timeout=120)
            count,duration=imageio_ffmpeg.count_frames_and_secs(str(clip))
            if count!=expected:raise ValueError(f'Frame count mismatch {count} vs {expected}')
            prediction=predict_clip(clip)
        except Exception as exc:
            prediction=dict(predicted_label='abstain',extraction_status='error',error=str(exc))
            count=None;duration=None
        records.append(dict(attemptId=attempt,truth=truth,truthSource='Nominal protocol label for scoring only; not measured rotation.',
                            sourceSha256=item['sourceSha256'],lastContact=item['lastContact'],firstContact=item['firstContact'],
                            firstSourceFrame=start,lastSourceFrame=end,expectedFrameCount=expected,actualFrameCount=count,duration=duration,
                            clip=str(clip),exportCommand=command,prediction=prediction))
        result=dict(scope='ORACLE TIMING, positive-only diagnostic; manual contacts supplied. NOT automatic localization, NOT specificity or underrotation accuracy.',
                    fixedContextSeconds=.24,fps=50,records=records,expectedCount=23,complete=len(records)==23,
                    metrics=evaluate([r['truth'] for r in records],[r['prediction']['predicted_label'] for r in records]),
                    modelSha256=sha(TRUSTED_ARTIFACT),inputSha256={str(contacts_path):sha(contacts_path),str(labels_path):sha(labels_path)})
        (output/'results.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(dict(completed=len(records),total=23,status=prediction['extraction_status'])),flush=True)
    print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':main()
