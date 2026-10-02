"""Offline hypotheses only. Does not modify viewer, baseline poses or labels."""
import hashlib
import json
from pathlib import Path
from pose_identity import CONFIG, propose, apply
from rtmpose_adapter import evaluate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/pose-identity-pilot-v1'

def main():
    OUT.mkdir(exist_ok=True)
    demo=json.loads((ROOT/'data/axel-demo-v1/data.json').read_text())
    predictions={'RTMPose':{},'Temporal hypothesis':{}}
    refs=[];all_proposals=[];hashes={}
    for version in ('v1','v2'):
        path=ROOT/f'data/pose-joint-review-{version}/user-annotations.json'
        refs+=json.loads(path.read_text())['frames']
        hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for c in demo['clips']:
        path=ROOT/'data/pose-rtmpose-pilot-v1'/f"{c['id']}.json"
        raw=json.loads(path.read_text());hashes[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        proposals=propose(raw['frames'],demo['width'],demo['height'])
        corrected=apply(raw['frames'],proposals)
        for label,frames in [('RTMPose',raw['frames']),('Temporal hypothesis',corrected)]:
            for f in frames:predictions[label][c['id'],f['frameIndex']]=f['landmarks']
        # Identity outputs deliberately use a separate proposal format, not a raw model claim.
        (OUT/(c['id']+'.json')).write_text(json.dumps(dict(attemptId=c['id'],sourceModel=raw['model'],proposals=proposals,frames=corrected),indent=2))
        all_proposals.extend(dict(attemptId=c['id'],**v) for v in proposals)
    result=evaluate(refs,predictions)
    result.update(config=CONFIG,sourceHashes=hashes,proposals=all_proposals,
        method='Fixed rules before evaluation. No manual labels used by the algorithm. Side-name hypotheses only; same point coordinates/scores. Six diagnostic frames are not a representative independent benchmark.')
    (OUT/'evaluation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ('models','proposals')},indent=2))

if __name__=='__main__':main()
