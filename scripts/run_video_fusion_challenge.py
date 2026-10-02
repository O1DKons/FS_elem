"""Apply frozen fusion model to existing26 coarse challenge clips; no training."""
import json
from video_fusion_type import ROOT,TRUSTED_ARTIFACT,predict_clip
from video_type_model import sha
from video_pose_type import evaluate


def main():
    source=ROOT/'work/video-type-challenge/results.json'
    prior=json.loads(source.read_text());records=[]
    output=ROOT/'work/video-fusion-challenge';output.mkdir(parents=True,exist_ok=True)
    for item in prior['records']:
        video=ROOT/'data/step3-candidates/clips'/(item['attemptId']+'.mp4')
        if sha(video)!=item['prediction']['video_sha256']:raise ValueError('Challenge video source changed')
        try:prediction=predict_clip(video)
        except Exception as exc:prediction=dict(predicted_label='abstain',extraction_status='error',error=str(exc),video_sha256=sha(video))
        records.append(dict(attemptId=item['attemptId'],truth=item['truth'],truthSource=item.get('truthSource'),prediction=prediction))
        print(json.dumps(dict(completed=len(records),total=len(prior['records']),status=prediction['extraction_status'])),flush=True)
        result=dict(records=records,metrics=evaluate([r['truth'] for r in records],[r['prediction']['predicted_label'] for r in records]),
                    source_sha256=sha(source),model_sha256=sha(TRUSTED_ARTIFACT),
                    scope='Existing26coarseclips domain challenge; no threshold/model tuning; not full-program benchmark.')
        (output/'results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':main()
