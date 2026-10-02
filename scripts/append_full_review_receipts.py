"""Append immutable complete-review receipts to a new, quarantined corpus snapshot."""
import argparse
from collections import Counter
import copy
import json
import os
from pathlib import Path
import tempfile

from axel_corpus import validate_corpus, validate_splits
from import_full_program_review import _json, _source_sha, validate_review
from pose_cache_contract import sha
from verify_axel_corpus import verify

ROOT = Path(__file__).resolve().parents[1]


def reference(path):
    path = Path(path).resolve()
    try:
        name = str(path.relative_to(ROOT))
    except ValueError:
        name = str(path)
    return dict(path=name, sha256=sha(path))


def load_packet(archive):
    """Check bytes, repeat semantic validation and rehash the source; never repair."""
    archive = Path(archive).resolve()
    names = {'review.json', 'manifest.json', 'validated.json', 'receipt.json'}
    if not archive.is_dir() or {p.name for p in archive.iterdir()} != names:
        raise ValueError('Incomplete or unexpected review packet')
    documents = {name:_json((archive/name).read_bytes()) for name in names}
    if any(not isinstance(doc, dict) for doc in documents.values()):
        raise ValueError('Review packet documents must be objects')
    receipt, raw, manifest, validated = (documents[name] for name in
        ['receipt.json', 'review.json', 'manifest.json', 'validated.json'])
    digest = sha(archive/'review.json')
    if receipt.get('schemaVersion') != 1 or receipt.get('reviewSha256') != digest or archive.name != digest:
        raise ValueError('Receipt identity differs from immutable review')
    expected_hashes = {name:sha(archive/name) for name in names-{'receipt.json'}}
    if receipt.get('fileSha256') != expected_hashes or receipt.get('manifestSha256') != expected_hashes['manifest.json']:
        raise ValueError('Review packet payload checksum mismatch')
    if receipt.get('importerSha256') != sha(ROOT/'scripts/import_full_program_review.py'):
        raise ValueError('Importer version changed; explicit compatibility review required')
    for flag in ['qaOnly', 'modelTrainingEligible', 'independentConfirmationVerified',
                 'trainingPerformed', 'predictionsProduced', 'measuredRotationProduced']:
        if receipt.get(flag) is not False:
            raise ValueError('Unsafe or unknown receipt scope: '+flag)
    if raw.get('qaOnly') is True or raw.get('qualityAssuranceOnly') is True or validated.get('qaOnly') is not False:
        raise ValueError('QA-only material is not expert evidence')
    items = manifest.get('items')
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise ValueError('Invalid manifest targets')
    targets = [row for row in items if row.get('reviewId') == raw.get('reviewId')]
    if len(targets) != 1:
        raise ValueError('Ambiguous or missing receipt target')
    target = targets[0]
    replayed = {**validate_review(raw, target), 'qaOnly':False}
    if validated != replayed or receipt.get('reviewId') != replayed['reviewId'] or receipt.get('sourceSha256') != replayed['sourceSha256']:
        raise ValueError('Validated receipt does not replay from original review')
    summary = dict(events=len(replayed['events']),
        axels=sum(e['family']=='axel' for e in replayed['events']),
        otherJumps=sum(e['family']=='other' for e in replayed['events']),
        uncertain=sum(e['family'] is None for e in replayed['events']))
    if receipt.get('summary') != summary:
        raise ValueError('Receipt counts do not replay')
    path = target.get('sourcePath')
    if not isinstance(path, str) or not path or not (ROOT/path).is_file() or _source_sha(ROOT/path) != replayed['sourceSha256']:
        raise ValueError('Source media unavailable or changed')
    return dict(receipt=receipt, validated=validated, target=target, mediaVerified=True,
                evidence=[reference(archive/name) for name in sorted(names)])


def _append_unique(rows, value):
    if value not in rows:
        rows.append(copy.deepcopy(value))


def merge_receipts(sources, events, partitions, packets, policy, evidence):
    """Keep prior observations; quarantine new labels and close development groups."""
    validate_corpus(sources, events)
    validate_splits(sources, partitions)
    if partitions.get('confirmation'):
        raise ValueError('Existing confirmation needs an explicit separate split review')
    if policy.get('schemaVersion') != 1 or policy.get('useScope') != 'development_only_quarantined':
        raise ValueError('Unsupported intake policy')
    for flag in ['physicalCaptureTimebaseVerified', 'physicalContactsVerified', 'globallyVerifiedAthleteIdentity']:
        if policy.get(flag) is not False:
            raise ValueError('Intake cannot certify timing, contacts or global identity')
    updated, observations = copy.deepcopy(sources), copy.deepcopy(events)
    by_hash = {s['sourceSha256']:s for s in updated}
    by_id = {e['eventId']:e for e in observations}
    imported = set()
    for item in packets:
        receipt, valid, target = item['receipt'], item['validated'], item['target']
        if (receipt.get('qaOnly') is not False or valid.get('qaOnly') is not False
                or valid.get('reviewComplete') is not True or item.get('mediaVerified') is not True):
            raise ValueError('Only complete non-QA reviews with verified source bytes may be appended')
        h = valid['sourceSha256']; imported.add(h)
        if target['sourceSha256'] != h:
            raise ValueError('Target source differs from review')
        if h not in by_hash:
            row = dict(sourceSha256=h, paths=[target['sourcePath']], collections=['full-review-receipt'],
                athleteIds=['unverified-source:'+h], athleteId='unverified-source:'+h,
                athleteLabels=[], athleteIdentityVerified=False,
                athleteIdentityScope='unverified; conservative groups are exclusions, not identity proof',
                originalRecordingId='exact-file:'+h, recordingGroupVerified=False,
                recordingIdentityStatus='exact_file_only', completeReviews=[], usedInDevelopment=True,
                provenance=[], metadataObservations=[], availablePaths=[target['sourcePath']],
                verifiedPaths=[target['sourcePath']], mediaHashVerified=True)
            updated.append(row); by_hash[h] = row
        row = by_hash[h]
        row['usedInDevelopment'] = True
        _append_unique(row.setdefault('paths', []), target['sourcePath'])
        _append_unique(row.setdefault('availablePaths', []), target['sourcePath'])
        _append_unique(row.setdefault('verifiedPaths', []), target['sourcePath'])
        row['mediaHashVerified'] = True
        _append_unique(row.setdefault('metadataObservations', []), dict(reviewId=valid['reviewId'],
            sourceFps=valid['fps'], sourceFrames=valid['sourceFrames'],
            duration=valid['durationSeconds'], physicalCaptureTimebaseVerified=False))
        raw_ref = next(ref for ref in item['evidence'] if Path(ref['path']).name == 'review.json')
        _append_unique(row['completeReviews'], raw_ref)
        if len(row['completeReviews']) > 1:
            row['reviewRevisionsRequireSelection'] = True
        for ref in item['evidence']+[evidence]:
            _append_unique(row['provenance'], ref)
        for event in valid['events']:
            observation = dict(eventId='full-receipt:'+receipt['reviewSha256']+':'+event['id'],
                originalEventId=event['id'], sourceSha256=h, reviewSha256=receipt['reviewSha256'],
                reviewId=valid['reviewId'], labelScope='full_review', reviewComplete=True,
                family=event['family'], nominal=event['nominal'],
                reportedElementCode=event['reportedElementCode'],
                reportedRotationAssessment=event['reportedRotationAssessment'],
                lastContactFrame=event['lastContactFrame'], firstContactFrame=event['firstContactFrame'],
                startSeconds=event['startSeconds'], endSeconds=event['endSeconds'],
                boundaryStatus='navigation_anchors_physical_contacts_unverified',
                timebase='exported-file playback seconds; physical capture timing unverified',
                captureTimebaseVerified=False, physicalContactsVerified=False,
                physicalFlightSeconds=None, physicalAirborneTurns=None,
                measuredUnderrotation=None, underrotation=None, modelTrainingEligible=False,
                eligibleTrainingTargets=[], availableLabelTargets=['family', 'nominal'] if event['family']=='axel'
                    else ['family'] if event['family']=='other' else [],
                provenance=copy.deepcopy(item['evidence']+[evidence]))
            identifier = observation['eventId']
            if identifier in by_id:
                if by_id[identifier] != observation:
                    raise ValueError('Same immutable observation has conflicting content')
            else:
                observations.append(observation); by_id[identifier] = observation
    groups = policy.get('conservativeGroups', [])
    names = set()
    for group in groups:
        name, hashes = group['exclusionGroup'], group['sourceHashes']
        if not isinstance(name, str) or not name or name in names or not hashes or len(hashes)!=len(set(hashes)) or not set(hashes)<=set(by_hash):
            raise ValueError('Invalid conservative exclusion group')
        names.add(name)
        for h in hashes:
            row = by_hash[h]
            _append_unique(row['athleteIds'], name)
            _append_unique(row.setdefault('conservativeExclusionGroups', []), name)
            _append_unique(row['provenance'], evidence)
    for pair in policy.get('sameAttemptSourcePairs', []):
        hashes = pair['sourceHashes']
        if (len(hashes)!=2 or len(set(hashes))!=2 or not set(hashes)<=set(by_hash)
                or pair.get('relation')!='human_confirmed_same_attempt_other_camera'
                or not isinstance(pair.get('eventCorrespondence'), str)
                or not any(set(hashes)<=set(g['sourceHashes']) for g in groups)):
            raise ValueError('Camera pair needs known sources and a shared conservative exclusion')
        linked = {**copy.deepcopy(pair), 'provenance':[copy.deepcopy(evidence)]}
        for h in hashes:
            _append_unique(by_hash[h].setdefault('sameAttemptCameraPairs', []), linked)
    development = set(partitions['development']) | imported
    previous = None
    while previous != len(development):
        previous = len(development)
        athletes = {a for s in updated if s['sourceSha256'] in development for a in s.get('athleteIds', [])}
        recordings = {s['originalRecordingId'] for s in updated
            if s['sourceSha256'] in development and s.get('originalRecordingId')}
        development.update(s['sourceSha256'] for s in updated if set(s.get('athleteIds', [])) & athletes
            or s.get('originalRecordingId') in recordings)
    split = dict(development=sorted(development), confirmation=[],
                 unassigned_needs_usage_audit=sorted(set(by_hash)-development))
    validate_corpus(updated, observations)
    validate_splits(updated, split)
    return updated, observations, split


def append_snapshot(base, policy_path, output):
    base, policy_path, output = (Path(p).resolve() for p in (base, policy_path, output))
    if output.exists():
        raise ValueError('Use a new output directory; never overwrite a corpus snapshot')
    base_verification = verify(base)
    base_hashes = _json((base/'SHA256SUMS.json').read_bytes())
    policy = _json(policy_path.read_bytes())
    if policy.get('baseManifestSha256') != sha(base/'SHA256SUMS.json'):
        raise ValueError('Intake policy is not bound to this base snapshot')
    inputs = dict(policy['inputSha256'])
    for path, digest in inputs.items():
        if sha(ROOT/path) != digest:
            raise ValueError('Intake evidence changed: '+path)
    if len(policy['receipts']) != len(set(policy['receipts'])) or not policy['receipts']:
        raise ValueError('Receipt paths must be nonempty and unique')
    packets = [load_packet(ROOT/path) for path in policy['receipts']]
    read = lambda name:_json((base/name).read_bytes())
    source_doc, event_doc, splits, report = (read(name) for name in
        ['sources.json', 'events.json', 'splits.json', 'intake-report.json'])
    ref = reference(policy_path)
    updated, observations, partitions = merge_receipts(source_doc['sources'], event_doc['events'],
        splits['partitions'], packets, policy, ref)
    for path in [base/name for name in base_hashes]+[base/'SHA256SUMS.json', policy_path,
                 Path(__file__), ROOT/'tests/test_append_full_review_receipts.py',
                 ROOT/'scripts/import_full_program_review.py']:
        item = reference(path); inputs[item['path']] = item['sha256']
    for packet in packets:
        for item in packet['evidence']:
            inputs[item['path']] = item['sha256']
    for path, digest in inputs.items():
        if path in report['inputSha256'] and report['inputSha256'][path] != digest:
            raise ValueError('Contradictory evidence digest: '+path)
    report['inputSha256'].update(inputs)
    new_ids = {e['eventId'] for e in observations}-{e['eventId'] for e in event_doc['events']}
    added = [e for e in observations if e['eventId'] in new_ids]
    report['receiptExtension'] = dict(baseManifestSha256=sha(base/'SHA256SUMS.json'),
        baseSnapshot=str(base.relative_to(ROOT)), policy=ref, baseVerification=base_verification,
        sourcesAdded=len(updated)-len(source_doc['sources']), observationsAdded=len(added),
        addedObservationsQuarantined=len(added), previousObservationsUnchanged=True,
        sourceMediaRechecked=True, timingTrainingPerformed=False, modelFittingPerformed=False,
        measuredRotationProduced=False, independentConfirmationVerified=False,
        cameraPairs=len(policy.get('sameAttemptSourcePairs', [])),
        note='Full-review labels retained as observations; camera copies are not independent attempts or accuracy evidence')
    for issue in policy.get('pendingDecisions', []):
        _append_unique(report.setdefault('unresolved', []), issue)
    summary = report['summary']
    summary.update(sourceFiles=len(updated), labelObservations=len(observations),
        scopes=dict(Counter(e['labelScope'] for e in observations)),
        fullyReviewedSourceFiles=sum(bool(s['completeReviews']) for s in updated),
        fullyReviewedAxelsByNominal=dict(Counter(e['nominal'] for e in observations
            if e['labelScope']=='full_review' and e['family']=='axel')),
        fullReviewTrainingEligibleAxelsByNominal=dict(Counter(e['nominal'] for e in observations
            if e['labelScope']=='full_review' and e['family']=='axel' and e.get('modelTrainingEligible'))),
        quarantinedFullReviewObservations=sum(e['labelScope']=='full_review' and
            not e.get('modelTrainingEligible') for e in observations),
        verifiedMediaSources=sum(bool(s['mediaHashVerified']) for s in updated),
        unresolvedIssues=len(report.get('unresolved', [])),
        developmentExcludedSources=len(partitions['development']),
        unassignedNeedsUsageAudit=len(partitions['unassigned_needs_usage_audit']))
    labelled = {e['sourceSha256'] for e in observations if e['family'] is not None}
    summary.update(selectedLabelSources=len(labelled),
        verifiedExpertLabelledMediaSources=sum(s['mediaHashVerified'] and s['sourceSha256'] in labelled for s in updated))
    splits.update(partitions=partitions, independenceVerified=False, status='not_frozen')
    splits['limitations'].append('New full-review receipt observations quarantined; capture timebase and global athlete identity unresolved')
    payloads = {name:(base/name).read_bytes() for name in base_hashes}
    for name, doc in [('sources.json', {**source_doc, 'sources':updated}),
                      ('events.json', {**event_doc, 'events':observations}),
                      ('splits.json', splits), ('intake-report.json', report)]:
        payloads[name] = (json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.review-corpus-', dir=output.parent) as directory:
        staging = Path(directory)/'snapshot'; staging.mkdir()
        for name, raw in payloads.items():
            (staging/name).write_bytes(raw)
        (staging/'SHA256SUMS.json').write_text(json.dumps({n:sha(staging/n) for n in payloads}, indent=2)+'\n')
        verify(staging)
        for packet in packets:
            target = packet['target']
            if _source_sha(ROOT/target['sourcePath']) != target['sourceSha256']:
                raise ValueError('Source changed before snapshot publication')
        if sha(base/'SHA256SUMS.json') != policy['baseManifestSha256']:
            raise ValueError('Base manifest changed before snapshot publication')
        os.rename(staging, output)
    return dict(snapshot=str(output), extension=report['receiptExtension'], verification=verify(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(append_snapshot(args.base, args.policy, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
