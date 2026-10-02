"""Freeze runtime-gated pivot proposals for two previously unassessed attempts."""
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from binary_pivot import pivot_features
from landing_rotation_model import fit_model, predict_item
from pivot_prospective import validate_candidates
from run_pivot_runtime_crossfit import attach_verified_source_indices, file_sha256

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_IDS = ('competition-40-02-01', 'competition-43-01-01')


def run(root=ROOT):
    root = Path(root).resolve()
    hashes = {}

    def read(relative):
        raw = (root / relative).read_bytes()
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    labels = read('data/rotation-expert-v1/resolved/revision-2/assessments.json')['assessments']
    workbook = read('data/axel-demo-v1/boot-workbench-data.json')
    review_doc = read('data/axel-demo-v1/rotation-review-data.json')
    boundaries = read('data/axel-boundaries-v1/manifest.json')['items']
    frozen = read('work/binary_pivot/results.json')
    if workbook['fps'] != 50 or review_doc['fps'] != 50:
        raise ValueError('Frozen pivot model requires the verified 50 fps timeline')

    work_by_id = {row['attemptId']: row for row in workbook['items']}
    review_by_id = {row['attemptId']: row for row in review_doc['items']}
    boundary_by_id = {row['attemptId']: row for row in boundaries}
    training_labels = [row for row in labels if row.get('rotationAssessment') in
                       ('apparently_complete', 'apparently_short')]
    training_records = {row['attemptId']: row for row in frozen['records']}
    frozen_features = {row['attemptId']: frozen['features'][index]
                       for index, row in enumerate(frozen['records'])}
    frozen_targets = {row['attemptId']: frozen['records'][index]['truth']
                      for index, row in enumerate(frozen['records'])}
    feature_rows, targets, model_rows = [], [], []
    for label in training_labels:
        attempt_id = label['attemptId']
        item = work_by_id[attempt_id]
        if item['sourceSha256'] != label['sourceSha256']:
            raise ValueError('Training source mismatch: ' + attempt_id)
        features = pivot_features(item)
        saved = np.asarray([np.nan if value is None else value
                            for value in frozen_features[attempt_id]], dtype=float)
        if not np.allclose(features, saved, equal_nan=True):
            raise ValueError('Training features differ from frozen baseline: ' + attempt_id)
        truth = int(label['rotationAssessment'] == 'apparently_short')
        if frozen_targets[attempt_id] != truth:
            raise ValueError('Frozen target mismatch: ' + attempt_id)
        feature_rows.append(features)
        targets.append(truth)
        model_rows.append(dict(attemptId=attempt_id, athlete=item['athlete'],
                               sourceSha256=item['sourceSha256']))
    if len(training_labels) != 20 or set(targets) != {0, 1}:
        raise ValueError('Expected exactly 20 clear visual training labels in both classes')

    candidates = []
    for attempt_id in CANDIDATE_IDS:
        item, review, boundary = work_by_id[attempt_id], review_by_id[attempt_id], boundary_by_id[attempt_id]
        if any(row['attemptId'] == attempt_id for row in labels):
            raise ValueError('Candidate already has an expert target: ' + attempt_id)
        if item['sourceSha256'] != review['sourceSha256'] or item['sourceSha256'] != boundary['sourceSha256']:
            raise ValueError('Candidate source hash mismatch: ' + attempt_id)
        if (item['lastContact'], item['firstContact']) != (review['lastContact'], review['firstContact']):
            raise ValueError('Candidate contact mismatch: ' + attempt_id)
        if any(boundary['boundaries'][key]['status'] != 'user_confirmed'
               for key in ('lastContact', 'firstContact')):
            raise ValueError('Candidate contacts are not user confirmed: ' + attempt_id)
        video_path = root / 'data/live/media' / (boundary['videoId'] + '.mp4')
        digest = file_sha256(video_path)
        if digest != item['sourceSha256']:
            raise ValueError('Candidate video hash mismatch: ' + attempt_id)
        hashes['sourceVideo:' + str(video_path.relative_to(root))] = digest
        candidates.append(dict(attemptId=attempt_id, athlete=item['athlete'],
                               sourceSha256=digest, item=item, review=review,
                               videoId=boundary['videoId']))
    validate_candidates(candidates, model_rows)

    db_path = root / 'data/live/fs-elem.sqlite'
    hashes['data/live/fs-elem.sqlite'] = file_sha256(db_path)
    connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        predictions = []
        model = fit_model(np.asarray(feature_rows), np.asarray(targets))
        for candidate in candidates:
            frame_times = {index: (index, seconds) for index, seconds in connection.execute(
                'SELECT frame_index, seconds FROM frame_times WHERE video_id=?',
                (candidate['videoId'],))}
            enriched, audit = attach_verified_source_indices(
                candidate['item'], candidate['review'], frame_times,
                root / 'data/axel-demo-v1')
            prediction = predict_item(enriched, model, workbook['fps'])
            predictions.append(dict(attemptId=candidate['attemptId'], athlete=candidate['athlete'],
                                    sourceSha256=candidate['sourceSha256'], sourceMapping=audit,
                                    prediction=prediction))
    finally:
        connection.close()

    for relative in ('scripts/binary_pivot.py', 'scripts/landing_rotation_model.py',
                     'scripts/run_pivot_runtime_crossfit.py', 'scripts/pivot_prospective.py'):
        hashes[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    return dict(schemaVersion=1,
                status='frozen_prospective_proposals_before_visual_expert_review',
                scope='Two previously unassessed, user-confirmed 2A attempts from the same event; both athletes and source videos excluded from the 20-attempt fit. Not an independent event test.',
                method='Unchanged nine-feature landing-pivot nearest-class-centroid model; fitted once to all 20 existing clear visual assessments with train-only imputation/scaling; runtime provenance gate enforced; no threshold tuning.',
                labelsUsed='Only the 20 existing clear visual assessments. No protocol calls, candidate outcome labels, or candidate metadata hints enter features or prediction.',
                training=dict(attemptCount=len(model_rows), classCounts=[int(sum(np.asarray(targets) == c)) for c in (0, 1)],
                              athletes=sorted({row['athlete'] for row in model_rows}),
                              sourceShas=sorted({row['sourceSha256'] for row in model_rows})),
                candidateCount=len(predictions), predictions=predictions,
                inputSha256=hashes,
                limitations=['Predictions are frozen before requested visual expert review and are not accuracy results until labels arrive.',
                             'Same event as training; athlete-held-out only, not an independent-event estimate.',
                             'Known Axel attempts and manually confirmed contacts; no full-program detection or revolution count.',
                             'The classifier estimates image-plane pivot completion, not physical underrotation degrees.'])


def main():
    output = ROOT / 'work/pivot-runtime-prospective-v1/results.json'
    if output.exists():
        raise ValueError('Refusing to overwrite frozen prospective predictions')
    result = run()
    result['scriptSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps([dict(attemptId=row['attemptId'], status=row['prediction']['status'],
                           rotationAssessment=row['prediction']['rotationAssessment'],
                           reason=row['prediction']['reason'])
                      for row in result['predictions']], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
