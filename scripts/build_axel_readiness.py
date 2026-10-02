#!/usr/bin/env python3
"""Read-only inventory of Axel supervision; never promotes protocol calls to truth."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3


def build(root):
    inputs = {}
    def read(relative):
        path = root / relative
        inputs[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text())
    rows = read('data/axel-boundaries-v1/manifest.json')['items']
    candidates = read('data/step3-candidates/manifest.json')['items']
    folds = read('data/axel-boundaries-v1/athlete-folds.json')['folds']
    items = []
    batch_frames = {}
    for row in rows:
        code = row['protocolCode'].split('+')[0]
        batchpath = f"data/pose-batch-v1/{row['attemptId']}.json"
        if (root / batchpath).exists():
            batch = read(batchpath)
            assert batch['sourceSha256'] == row['sourceSha256']
            batch_frames[row['attemptId']] = len(batch['frames'])
        posepath = f"data/pose-rtmpose-pilot-v1/{row['attemptId']}.json"
        pose = read(posepath) if (root / posepath).exists() else None
        if pose:
            assert pose['sourceSha256'] == row['sourceSha256']
        items.append(dict(attemptId=row['attemptId'], athlete=row['athleteGroup'],
            videoId=row['videoId'], sourceEvent=row['sourceEvent'], protocolComponent=code,
            rotationTarget=None, rotationTargetReason=row['protocolLabelUse'],
            confirmedContactFrames=sum(row['boundaries'][key]['status'] == 'user_confirmed'
                                       for key in ('lastContact', 'firstContact')),
            poseFrames=len(pose['frames']) if pose else 0))
    by_id = {r['attemptId']: r for r in items}
    assert len(by_id) == len(items)
    for fold in folds:
        train = [by_id[i] for i in fold['trainAttemptIds']]
        val = [by_id[i] for i in fold['validationAttemptIds']]
        assert {r['athlete'] for r in train}.isdisjoint(r['athlete'] for r in val)
        assert {r['videoId'] for r in train}.isdisjoint(r['videoId'] for r in val)
        assert {r['attemptId'] for r in train + val} == set(by_id)
    db = root / 'data/live/fs-elem.sqlite'
    with sqlite3.connect(f'{db.as_uri()}?mode=ro', uri=True) as connection:
        expert = [dict(videoId=v, attemptId=a, label=json.loads(p))
                  for v, a, p in connection.execute('SELECT video_id,attempt_id,payload FROM expert_labels')]
    double = [r for r in items if r['protocolComponent'].startswith('2A')]
    marked = sum('<' in r['protocolComponent'] for r in double)
    protocol = collections.Counter(r['protocolComponent'] for r in items)
    pose = [r for r in items if r['poseFrames']]
    return dict(schemaVersion=1, inputSha256=inputs,
        scope='Readiness audit, not trained-model evaluation; SQLite expert labels read live, not hashed.',
        counts=dict(confirmedAxels=len(items), athletes=len({r['athlete'] for r in items}),
            events=len({r['sourceEvent'] for r in items}), confirmedContactFrames=sum(r['confirmedContactFrames'] for r in items),
            protocolComponents=dict(protocol), poseClips=len(pose), poseFrames=sum(r['poseFrames'] for r in pose),
            mediaPipeBatchClips=len(batch_frames), mediaPipeBatchFrames=sum(batch_frames.values()),
            poseProtocolComponents=dict(collections.Counter(r['protocolComponent'] for r in pose)),
            candidateStatuses=dict(collections.Counter(r['status'] for r in candidates)),
            attemptLinkedExpertLabels=sum(r['attemptId'] is not None for r in expert)),
        protocolOnlyBinaryBaseline=dict(scope='2A first component only; < and << grouped as marked; unmarked does not mean clean',
            marked=marked, unmarked=len(double)-marked, majorityAccuracy=max(marked,len(double)-marked)/len(double),
            balancedAccuracyConstantPrediction=0.5, independentlyVerifiedRotationTargets=0),
        athleteFolds=dict(count=len(folds), athleteAndVideoDisjoint=True, externalEventTest=False),
        items=items, otherCandidateWindows=[{key:r.get(key) for key in ('id','athleteGroup','status','mappingStatus','protocolCode','sourceStart','sourceEnd')}
                                         for r in candidates if r['status'] != 'accepted_axel'],
        expertVideoLabels=expert,
        gates=dict(boundaryExperiment='ready_for_exploratory_athlete_held_out_evaluation',
                   fullProgramDetection='needs_exhaustive_jump_and_background_annotations',
                   rotationClassification='needs_attempt_linked_independent_rotation_labels'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, default=Path('work/step27-readiness/readiness.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    report = build(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report['counts'], ensure_ascii=False, indent=2))
    print(f"Protocol-only majority: {report['protocolOnlyBinaryBaseline']['majorityAccuracy']:.2%}")


if __name__ == '__main__':
    main()
