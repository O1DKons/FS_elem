"""Evaluate the frozen landing-pivot proxy against official 2A protocol calls."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from binary_pivot import FEATURES, pivot_features
from run_rotation_proxy_baseline import evaluate
from source_frame_reuse import independent_intervals


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT_RE = re.compile(r'competition-(\d+)-(\d+)-\d+')
COMPONENT_RE = re.compile(r'2A(<<|<|q)?\Z', re.I)


def protocol_target(code):
    """Return protocol short-call target; exclude invalid/repeated/other jumps."""
    match = COMPONENT_RE.fullmatch(code) if isinstance(code, str) else None
    if match is None:
        return None
    return int(match.group(1) is not None)


def protocol_2a_by_attempt(document):
    """Map each single 2A component to its event attempt identity."""
    result = {}
    for program in document.get('programs', []):
        for element in program.get('elements', []):
            components = [c for c in element.get('jumpComponents', []) if protocol_target(c) is not None]
            if len(components) > 1:
                raise ValueError('Multiple 2A components need distinct attempt identities')
            if not components:
                continue
            key = f"competition-{int(program['startNumber']):02d}-{int(element['sequence']):02d}-01"
            if key in result:
                raise ValueError('Duplicate 2A attempt identity: ' + key)
            result[key] = dict(attemptId=key, athlete=program['athlete'],
                               target=protocol_target(components[0]), code=components[0],
                               elementCode=element.get('code'), fall=element.get('fall'),
                               videoPath=program.get('videoPath'), startNumber=int(program['startNumber']),
                               sequence=int(element['sequence']))
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(root=ROOT):
    hashes = {}

    def read(relative):
        path = root / relative
        raw = path.read_bytes()
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    event = read('data/competition/competition-2026-09-14-17.json')
    boundary_doc = read('data/axel-boundaries-v1/manifest.json')
    boot_doc = read('data/axel-demo-v1/boot-workbench-data.json')
    expert_doc = read('data/rotation-expert-v1/resolved/revision-2/assessments.json')
    protocol_rows = protocol_2a_by_attempt(event)
    boundaries = {row['attemptId']: row for row in boundary_doc['items']}
    boot_items = {row['attemptId']: row for row in boot_doc['items']}
    expert_rows = {row['attemptId']: row for row in expert_doc['assessments']}
    videos = {}
    records, feature_rows, runtime_rows, excluded = [], [], [], []

    for attempt_id, protocol in sorted(protocol_rows.items()):
        boundary = boundaries.get(attempt_id)
        item = boot_items.get(attempt_id)
        if boundary is None or item is None:
            excluded.append(dict(attemptId=attempt_id, reason='No saved manual boundary/boot feature window'))
            continue
        for key in ('lastContact', 'firstContact'):
            if boundary['boundaries'][key]['status'] != 'user_confirmed':
                raise ValueError('Unconfirmed contact boundary: ' + attempt_id + ' ' + key)
        if not protocol['videoPath']:
            raise ValueError('Missing official protocol video path: ' + attempt_id)
        source_path = Path(protocol['videoPath'])
        if not source_path.is_file():
            raise ValueError('Missing source video: ' + str(source_path))
        source_key = str(source_path)
        if source_key not in videos:
            videos[source_key] = sha256(source_path)
        source_digest = videos[source_key]
        hashes['sourceVideo:' + source_key] = source_digest
        if source_digest != boundary['sourceSha256'] or source_digest != item['sourceSha256']:
            raise ValueError('Protocol/source provenance mismatch: ' + attempt_id)
        first_contact = boundary['boundaries']['firstContact']['frameIndex']
        if item['firstContact'] != first_contact:
            raise ValueError('Boundary/workbench contact mismatch: ' + attempt_id)
        if item['athlete'] != protocol['athlete'] or boundary['athleteGroup'] != protocol['athlete']:
            raise ValueError('Athlete identity mismatch: ' + attempt_id)
        if boundary['protocolCode'] != protocol['elementCode']:
            raise ValueError('Official call differs from boundary manifest: ' + attempt_id)

        features = pivot_features(item)
        feature_rows.append(features)
        runtime_evidence = independent_intervals(item)
        runtime_rows.append(runtime_evidence)
        expert = expert_rows.get(attempt_id, {}).get('rotationAssessment')
        records.append(dict(attemptId=attempt_id, athlete=protocol['athlete'],
                            sourceSha256=source_digest, protocolCode=protocol['code'],
                            officialElementCode=protocol['elementCode'],
                            target=protocol['target'], officialFall=protocol['fall'],
                            priorVisualExpertAssessment=expert,
                            visibleFrames=int(round(features[0] * 11)),
                            adjacentIntervals=int(round(features[1] * 10)),
                            runtimeSourceEvidence=runtime_evidence,
                            featureValues=[float(v) if np.isfinite(v) else None for v in features]))

    x = np.asarray(feature_rows, dtype=float)
    y = np.asarray([row['target'] for row in records], dtype=int)
    groups = np.asarray([row['athlete'] for row in records])
    if not records or len(np.unique(y)) != 2:
        raise ValueError('Need mapped protocol examples from both target classes')
    # This is the pre-existing deployed centroid rule; no model/feature tuning here.
    centroid = evaluate(x, y, groups)
    majority = evaluate(x[:, :1], y, groups, majority=True)
    for fold in centroid['folds']:
        train, test = fold['trainIndices'], fold['testIndices']
        if {records[i]['athlete'] for i in train} & {records[i]['athlete'] for i in test}:
            raise ValueError('Athlete leaked across a held-out fold')
        for index in test:
            if any(records[j]['sourceSha256'] == records[index]['sourceSha256'] for j in train):
                raise ValueError('Source video leaked across a held-out fold')

    disagreements = [r['attemptId'] for r in records if
                     r['priorVisualExpertAssessment'] in ('apparently_complete', 'apparently_short') and
                     int(r['priorVisualExpertAssessment'] == 'apparently_short') != r['target']]
    return dict(schemaVersion=1,
                scope='Exploratory same-event athlete-held-out diagnostic against official protocol calls; not independent event validation or physical angle measurement',
                classes={'0': 'official 2A without q/< /<< call',
                         '1': 'official 2Aq, 2A<, or 2A<< call'},
                method='Pre-existing nine-feature landing-pivot nearest-centroid rule; per-athlete outer holdout; train-only imputation/scaling; no tuning or threshold selection',
                protocolCounts={code: sum(r['protocolCode'] == code for r in records)
                                for code in ('2A', '2Aq', '2A<', '2A<<')},
                metrics={'centroid': centroid['metrics'], 'trainingMajority': majority['metrics']},
                runtimeGate=dict(total=len(runtime_rows), eligible=sum(
                    e['sourceProvenanceComplete'] and e['independentSourceIntervals'] >= 3
                    for e in runtime_rows),
                    rule='Complete original-frame provenance and at least three independent adjacent source intervals'),
                expertProtocolDisagreements=disagreements,
                inputSha256=hashes,
                scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                featureNames=FEATURES, records=records, folds=centroid['folds'], excluded=excluded,
                limitations=['All source videos are identical to the previously inspected single-event development corpus.',
                              'Event protocol calls are supervised targets, not measured rotation degrees or independent expert re-review.',
                              'Manual takeoff/landing boundaries and precomputed boot candidates are used; no full-program Axel detection.',
                              'Saved landing candidates lack the original-frame provenance required by current runtime abstention gate.',
                              'Two prior visual-expert labels disagree with the official protocol-derived binary target.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=Path('work/protocol-pivot-crossfit/results.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    result = run(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
