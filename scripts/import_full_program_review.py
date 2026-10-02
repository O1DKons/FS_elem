"""Import complete video reviews with immutable evidence; do not train or score."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
AXEL = re.compile(r'([1-4]A)(?:q|<<|<)?', re.IGNORECASE)


def _positive(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive and finite')
    return float(value)


def validate_review(review, target):
    """Validate against independent source metadata, retaining uncertainty."""
    if not isinstance(review, dict) or not isinstance(target, dict):
        raise ValueError('Review and target must be objects')
    if type(review.get('schemaVersion')) is not int or review['schemaVersion'] != 1:
        raise ValueError('Review schemaVersion must be integer 1')
    if review.get('coverageReviewed') is not True:
        raise ValueError('Complete source coverage must be explicitly confirmed')
    identity = target.get('reviewId')
    if not isinstance(identity, str) or not identity.strip() or review.get('reviewId') != identity:
        raise ValueError('Review ID does not match manifest')
    source = target.get('sourceSha256')
    if not isinstance(source, str) or not re.fullmatch(r'[a-f0-9]{64}', source):
        raise ValueError('Manifest source SHA256 is invalid')
    if review.get('sourceSha256') != source:
        raise ValueError('Review source SHA256 does not match manifest')
    frames = target.get('sourceFrames')
    if type(frames) is not int or frames <= 0:
        raise ValueError('Manifest sourceFrames must be a positive integer')
    fps = _positive(target.get('fps'), 'Manifest fps')
    duration = _positive(target.get('durationSeconds'), 'Manifest durationSeconds')
    if abs(duration - frames/fps) > 0.25:
        raise ValueError('Manifest timebase is inconsistent')
    if abs(_positive(review.get('fps'), 'Review fps') - fps) > 1e-8:
        raise ValueError('Review fps does not match manifest')
    review_duration = _positive(review.get('durationSeconds'), 'Review durationSeconds')
    if abs(review_duration - duration) > 0.25 or abs(review_duration - frames/fps) > 0.25:
        raise ValueError('Review duration does not match manifest')
    if not isinstance(review.get('events'), list):
        raise ValueError('Review events must be a list')

    events, seen, confirmed = [], set(), []
    for row in review['events']:
        if not isinstance(row, dict):
            raise ValueError('Each event must be an object')
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError('Event IDs must be nonempty and unique')
        seen.add(identifier)
        kind = row.get('eventClass')
        if kind not in ('axel', 'other_jump', 'uncertain'):
            raise ValueError(f'Unsupported event class: {identifier}')
        last, first = row.get('lastContactFrame'), row.get('firstContactFrame')
        if type(last) is not int or type(first) is not int or not 0 <= last < first < frames:
            raise ValueError(f'Invalid source contacts: {identifier}')
        code = row.get('elementCode')
        if code is not None and not isinstance(code, str):
            raise ValueError(f'Element code must be text: {identifier}')
        match = AXEL.fullmatch(code.strip()) if isinstance(code, str) else None
        if kind == 'axel' and match is None:
            raise ValueError(f'Confirmed Axel needs a valid nominal code: {identifier}')
        if kind == 'other_jump' and match is not None:
            raise ValueError(f'Axel code contradicts other_jump: {identifier}')
        if kind != 'uncertain':
            confirmed.append((last, first, identifier))
        nominal = match.group(1).upper() if kind == 'axel' else None
        events.append(dict(id=identifier, eventClass=kind,
            family='axel' if kind == 'axel' else 'other' if kind == 'other_jump' else None,
            nominal=nominal, targetNominalSupported=nominal in ('1A', '2A') if nominal else None,
            reportedElementCode=code, reportedRotationAssessment=row.get('rotationAssessment'),
            lastContactFrame=last, firstContactFrame=first,
            startSeconds=last/fps, endSeconds=first/fps,
            physicalAirborneTurns=None, measuredUnderrotation=None, underrotation=None))
    confirmed.sort()
    for previous, current in zip(confirmed, confirmed[1:]):
        if current[0] < previous[1]:
            raise ValueError(f'Confirmed flight interiors overlap: {previous[2]}, {current[2]}')
    return dict(schemaVersion=1, reviewId=identity, sourceSha256=source,
        sourceFrames=frames, fps=fps, durationSeconds=duration, reviewComplete=True,
        reviewedAt=review.get('reviewedAt'), events=events, modelTrainingEligible=False,
        splitAssignmentRequired=True, independentConfirmationVerified=False,
        scope='Expert full-program observations only; nominal labels are not measured physical rotations')


def _json(raw):
    def reject(value):
        raise ValueError(f'Nonfinite JSON literal: {value}')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    return json.loads(raw, parse_constant=reject, object_pairs_hook=unique)


def _sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _source_sha(path):
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Source changed while hashing')
    return digest


def _encoded(document):
    return (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()


def import_review(review_path, manifest_path, output, *, qa_only=False):
    """Archive original bytes and a validated receipt; replay never overwrites."""
    review_path, manifest_path, output = map(Path, (review_path, manifest_path, output))
    raw, manifest_raw = review_path.read_bytes(), manifest_path.read_bytes()
    review, manifest = _json(raw), _json(manifest_raw)
    if not isinstance(review, dict) or not isinstance(manifest, dict):
        raise ValueError('Review and manifest must be JSON objects')
    marked_qa = (review.get('qaOnly') is True or review.get('qualityAssuranceOnly') is True
                 or 'qa-only' in review_path.parts)
    if marked_qa and not qa_only:
        raise ValueError('QA input cannot be imported as expert evidence')
    items = manifest.get('items')
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise ValueError('Manifest items must be objects')
    targets = [row for row in items if row.get('reviewId') == review.get('reviewId')]
    if len(targets) != 1:
        raise ValueError('Review must match exactly one manifest target')
    target = targets[0]
    validated = validate_review(review, target)
    source_path = target.get('sourcePath')
    if not isinstance(source_path, str) or not source_path:
        raise ValueError('Manifest target needs sourcePath')
    media = Path(source_path)
    media = media if media.is_absolute() else ROOT/media
    if not media.is_file() or _source_sha(media) != target['sourceSha256']:
        raise ValueError('Original source media is unavailable or has changed')
    validated['qaOnly'] = bool(qa_only)
    payloads = {'review.json':raw, 'manifest.json':manifest_raw,
                'validated.json':_encoded(validated)}
    hashes = {name:_sha_bytes(value) for name, value in payloads.items()}
    digest = hashes['review.json']
    stable_receipt = dict(schemaVersion=1, reviewId=validated['reviewId'],
        sourceSha256=validated['sourceSha256'], reviewSha256=digest,
        manifestSha256=hashes['manifest.json'], fileSha256=hashes,
        qaOnly=bool(qa_only), modelTrainingEligible=False,
        independentConfirmationVerified=False, trainingPerformed=False,
        predictionsProduced=False, measuredRotationProduced=False,
        summary=dict(events=len(validated['events']),
            axels=sum(e['family']=='axel' for e in validated['events']),
            otherJumps=sum(e['family']=='other' for e in validated['events']),
            uncertain=sum(e['family'] is None for e in validated['events'])))
    destination = output/digest

    def verify_existing():
        if not destination.is_dir() or {p.name for p in destination.iterdir()} != set(payloads)|{'receipt.json'}:
            raise ValueError('Existing import is incomplete or has extra files')
        for name, value in payloads.items():
            if (destination/name).read_bytes() != value:
                raise ValueError('Immutable import differs: '+name)
        saved = _json((destination/'receipt.json').read_bytes())
        if not isinstance(saved, dict) or any(saved.get(k) != v for k,v in stable_receipt.items()):
            raise ValueError('Immutable receipt differs; QA scope cannot be promoted')
        return destination

    if destination.exists():
        return verify_existing()
    output.mkdir(parents=True, exist_ok=True)
    receipt = {**stable_receipt, 'importedUtc':datetime.now(timezone.utc).isoformat(),
               'importerSha256':_sha_bytes(Path(__file__).read_bytes())}
    with tempfile.TemporaryDirectory(prefix='.review-intake-', dir=output) as directory:
        staging = Path(directory)/'archive'
        staging.mkdir()
        for name, value in {**payloads, 'receipt.json':_encoded(receipt)}.items():
            with (staging/name).open('xb') as stream:
                stream.write(value)
        try:
            os.rename(staging, destination)
        except OSError:
            if not destination.exists():
                raise
            return verify_existing()
    return verify_existing()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--qa-only', action='store_true')
    args = parser.parse_args()
    archive = import_review(args.review, args.manifest, args.output, qa_only=args.qa_only)
    receipt = _json((archive/'receipt.json').read_bytes())
    print(json.dumps(dict(archive=str(archive), qaOnly=receipt['qaOnly'],
                          **receipt['summary']), ensure_ascii=False))


if __name__ == '__main__':
    main()
