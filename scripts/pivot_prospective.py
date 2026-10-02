"""Validate identity and source separation for a prospective pivot evaluation."""


def validate_candidates(candidates, training_records):
    training_ids = {row['attemptId'] for row in training_records}
    training_athletes = {row['athlete'] for row in training_records}
    training_sources = {row['sourceSha256'] for row in training_records}
    candidate_ids = set()
    for row in candidates:
        attempt_id, athlete, source = row['attemptId'], row['athlete'], row['sourceSha256']
        if attempt_id in training_ids or attempt_id in candidate_ids:
            raise ValueError('Candidate already appears in labelled training/evaluation records')
        candidate_ids.add(attempt_id)
        if athlete in training_athletes:
            raise ValueError('Candidate athlete leakage into training')
        if source in training_sources:
            raise ValueError('Candidate source leakage into training')
    return candidates
