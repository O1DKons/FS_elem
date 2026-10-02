"""Cross-fit the frozen pivot rule with verified source-frame evidence and abstentions."""
import argparse
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from binary_pivot import pivot_features
from landing_rotation_model import fit_model, predict_item
from run_rotation_proxy_baseline import athlete_folds, evaluate


ROOT = Path(__file__).resolve().parents[1]
TIME_TOLERANCE_SECONDS = 0.002


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def attach_verified_source_indices(item, review_item, source_times, image_root,
                                   time_tolerance=TIME_TOLERANCE_SECONDS):
    """Add source indexes only after frame hash, image, and decoded-time checks."""
    result = copy.deepcopy(item)
    review_frames = {frame['frameIndex']: frame for frame in review_item['frames']}
    verified, maximum_time_delta, asset_hashes = 0, 0.0, []
    for frame in result['frames']:
        frame_index = frame['frameIndex']
        review = review_frames.get(frame_index)
        if review is None or review.get('sourceFrameSha256') != frame.get('sourceFrameSha256'):
            raise ValueError('Review/workbench frame identity mismatch: ' + str(frame_index))
        if review.get('image') != frame.get('image'):
            raise ValueError('Review/workbench frame path mismatch: ' + str(frame_index))
        path = Path(image_root) / review['image']
        actual_digest = file_sha256(path)
        if actual_digest != review['sourceFrameSha256']:
            raise ValueError('Frame asset hash mismatch: ' + str(path))
        source = source_times.get(frame_index)
        if source is None:
            raise ValueError('No original decoded frame-time row: ' + str(frame_index))
        source_index, source_time = source
        delta = abs(float(source_time) - float(review['time']))
        maximum_time_delta = max(maximum_time_delta, delta)
        if source_index != frame_index or delta > time_tolerance:
            raise ValueError('Source index/time mapping mismatch: ' + str(frame_index))
        frame['sourceFrameIndex'] = int(source_index)
        frame['sourceTime'] = float(source_time)
        verified += 1
        asset_hashes.append((review['image'], actual_digest))
    if verified != len(item['frames']):
        raise ValueError('Incomplete source-frame mapping')
    return result, dict(verifiedFrames=verified, maximumTimeDeltaSeconds=maximum_time_delta,
                        frameAssetsSha256=hashlib.sha256(json.dumps(sorted(asset_hashes),
                        separators=(',', ':')).encode()).hexdigest())


def scored_metrics(rows):
    confusion = [[0, 0, 0], [0, 0, 0]]  # complete, short, abstain
    for row in rows:
        column = row['prediction'] if row['prediction'] in (0, 1) else 2
        confusion[row['truth']][column] += 1
    support = [sum(row) for row in confusion]
    recalls = [confusion[i][i] / support[i] if support[i] else None for i in (0, 1)]
    correct = confusion[0][0] + confusion[1][1]
    present = [value for value in recalls if value is not None]
    answered = sum(confusion[i][0] + confusion[i][1] for i in (0, 1))
    return dict(total=sum(support), correct=correct,
                accuracyIncludingAbstentions=correct / sum(support),
                balancedAccuracyIncludingAbstentions=sum(present) / len(present) if present else None,
                recallComplete=recalls[0], recallShort=recalls[1],
                coverage=answered / sum(support), abstentions=confusion[0][2] + confusion[1][2],
                confusionTrueRowsPredictedColumnsCompleteShortAbstain=confusion)


def run(root=ROOT):
    root = Path(root).resolve()
    hashes = {}

    def read(relative):
        path = root / relative
        raw = path.read_bytes()
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    assessments = read('data/rotation-expert-v1/resolved/revision-2/assessments.json')['assessments']
    workbook = read('data/axel-demo-v1/boot-workbench-data.json')
    review_doc = read('data/axel-demo-v1/rotation-review-data.json')
    boundaries = read('data/axel-boundaries-v1/manifest.json')['items']
    prior = read('work/binary_pivot/results.json')
    if workbook.get('fps') != 50 or review_doc.get('fps') != 50:
        raise ValueError('Frozen pivot model requires the verified 50 fps timeline')

    db_path = root / 'data/live/fs-elem.sqlite'
    hashes['data/live/fs-elem.sqlite'] = file_sha256(db_path)
    connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        boot = {row['attemptId']: row for row in workbook['items']}
        reviews = {row['attemptId']: row for row in review_doc['items']}
        boundary_by_id = {row['attemptId']: row for row in boundaries}
        prior_records = {row['attemptId']: row for row in prior['records']}
        prior_feature_by_id = {row['attemptId']: prior['features'][index]
                               for index, row in enumerate(prior['records'])}
        prior_prediction_by_id = {row['attemptId']: prior['variants']['centroid']['predictions'][index]
                                  for index, row in enumerate(prior['records'])}
        mapped, audits, records, feature_rows = {}, {}, [], []
        for label in assessments:
            target = label.get('rotationAssessment')
            if target not in ('apparently_complete', 'apparently_short'):
                continue
            attempt_id = label['attemptId']
            item, review, boundary = boot[attempt_id], reviews[attempt_id], boundary_by_id[attempt_id]
            prior_record = prior_records[attempt_id]
            for key, value in (('sourceSha256', label['sourceSha256']),
                               ('firstContact', label['firstContact']),
                               ('lastContact', label['lastContact'])):
                if item.get(key) != value:
                    raise ValueError('Assessment/workbench provenance mismatch: ' + attempt_id + ' ' + key)
            if prior_record.get('sourceSha256') != label['sourceSha256']:
                raise ValueError('Assessment/frozen-feature source mismatch: ' + attempt_id)
            if item['athlete'] != boundary['athleteGroup'] or item['athlete'] != prior_record['athlete']:
                raise ValueError('Athlete identity mismatch: ' + attempt_id)
            if any(boundary['boundaries'][key]['status'] != 'user_confirmed'
                   for key in ('lastContact', 'firstContact')):
                raise ValueError('Contact is not manually confirmed: ' + attempt_id)
            video_path = root / 'data/live/media' / (boundary['videoId'] + '.mp4')
            source_digest = file_sha256(video_path)
            if source_digest != label['sourceSha256']:
                raise ValueError('Source video hash mismatch: ' + attempt_id)
            hashes['sourceVideo:' + str(video_path.relative_to(root))] = source_digest
            frame_times = {index: (index, seconds) for index, seconds in connection.execute(
                'SELECT frame_index, seconds FROM frame_times WHERE video_id=?', (boundary['videoId'],))}
            enriched, audit = attach_verified_source_indices(
                item, review, frame_times, root / 'data/axel-demo-v1')
            mapped[attempt_id], audits[attempt_id] = enriched, audit
            features = pivot_features(enriched)
            saved = np.asarray([np.nan if value is None else value
                                for value in prior_feature_by_id[attempt_id]], dtype=float)
            if not np.allclose(features, saved, equal_nan=True):
                raise ValueError('Reconstructed features differ from frozen baseline: ' + attempt_id)
            feature_rows.append(features)
            records.append(dict(attemptId=attempt_id, athlete=item['athlete'], sourceSha256=source_digest,
                                truth=int(target == 'apparently_short'), expertAssessment=target,
                                expertNotes=label.get('notes'), sourceMapping=audits[attempt_id]))
    finally:
        connection.close()

    x = np.asarray(feature_rows, dtype=float)
    y = np.asarray([row['truth'] for row in records], dtype=int)
    groups = np.asarray([row['athlete'] for row in records])
    saved_predictions = prior_prediction_by_id
    fold_rows, predictions = [], []
    for train, test in athlete_folds(groups):
        model = fit_model(x[train], y[train])
        if {records[i]['athlete'] for i in train} & {records[i]['athlete'] for i in test}:
            raise ValueError('Athlete leakage across outer fold')
        if {records[i]['sourceSha256'] for i in train} & {records[i]['sourceSha256'] for i in test}:
            raise ValueError('Source video leakage across outer fold')
        for index in test:
            row = records[index]
            prediction = predict_item(mapped[row['attemptId']], model, workbook['fps'])
            value = {'truth': row['truth'], 'prediction': 0 if prediction['rotationAssessment'] == 'apparently_complete'
                     else 1 if prediction['rotationAssessment'] == 'apparently_short' else None}
            predictions.append(dict(attemptId=row['attemptId'], **value,
                                    status=prediction['status'], reason=prediction['reason'],
                                    independentSourceIntervals=prediction['independentSourceIntervals'],
                                    trainingClassCounts=[int(sum(y[train] == c)) for c in (0, 1)],
                                    previousManualContactProposal=int(saved_predictions[row['attemptId']]),
                                    sameAsPreviousManualProposal=(value['prediction'] == saved_predictions[row['attemptId']]
                                                                  if value['prediction'] is not None else None)))
        fold_rows.append(dict(heldOutAthlete=str(groups[test[0]]), trainIndices=train.tolist(),
                              testIndices=test.tolist(), trainingClassCounts=[int(sum(y[train] == c)) for c in (0, 1)]))

    if len(records) != 20 or len(predictions) != len(records):
        raise ValueError('Expected exactly the 20 clear visual expert assessments')
    baseline = evaluate(x, y, groups, majority=True)
    result = dict(schemaVersion=1,
                  scope='Exploratory athlete-out visual-expert assessment; known 2A attempts and manual contacts; runtime evidence gate enforced; single previously inspected event',
                  method='Frozen landing-pivot nearest-centroid rule; per-athlete outer holdout; train-only imputation/scaling; no model or threshold tuning',
                  labels={'0': 'visual expert apparently complete', '1': 'visual expert apparently short (q included)'},
                  metrics=dict(model=scored_metrics(predictions), allShortMajority=evaluate(
                      x, y, groups, majority=True)['metrics']),
                  comparison=dict(previousUngatedManualContact=prior['variants']['centroid']['metrics'],
                                  predictionMatchesPriorOnAnswered=sum(p['sameAsPreviousManualProposal'] is True
                                                                       for p in predictions)),
                  sourceMapping=dict(method='User-captured frameIndex joined to read-only original decoded-frame time table; complete contact-window PNG SHA-256 check; per-frame timestamp tolerance 2 ms',
                                     verifiedFrames=sum(a['verifiedFrames'] for a in audits.values()),
                                     maximumTimeDeltaSeconds=max(a['maximumTimeDeltaSeconds'] for a in audits.values()),
                                     runtimeEvidenceEligible=sum(p['status'] == 'experimental_proposal' for p in predictions),
                                     attemptCount=len(records), perAttempt=audits),
                  inputSha256=hashes, scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  records=records, predictions=predictions, folds=fold_rows,
                  limitations=['Same inspected single-event development set; no external-event confirmation.',
                                'Known Axel boundaries; does not detect an Axel in a full program or measure revolutions/degrees.',
                                'Visual expert judgement is the target; official protocol calls remain a separate label source.',
                                'One item with fewer than three independent landing intervals abstains and counts as wrong.'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=Path('work/pivot-runtime-crossfit/results.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    result = run(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))
    print(json.dumps(result['sourceMapping'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
