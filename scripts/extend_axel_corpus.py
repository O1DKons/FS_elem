"""Create a new corpus snapshot with conservative identity links; never relabel."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

from axel_corpus import validate_corpus, validate_splits
from pose_cache_contract import sha
from verify_axel_corpus import verify

ROOT = Path(__file__).resolve().parents[1]


def apply_identity_links(sources, events, partitions, overlay, evidence):
    """Expand development exclusion by known links without certifying identities."""
    validate_corpus(sources, events)
    validate_splits(sources, partitions)
    if partitions.get('confirmation'):
        raise ValueError('Existing confirmation requires a separate split review')
    if overlay.get('globallyVerifiedIdentity') is not False or overlay.get('replacesRegistry') is not False:
        raise ValueError('Overlay must preserve registry and qualify identity uncertainty')
    by_hash = {row['sourceSha256']:row for row in overlay['sources']}
    if len(by_hash) != len(overlay['sources']) or set(by_hash) != {s['sourceSha256'] for s in sources}:
        raise ValueError('Overlay sources differ from base snapshot')
    declared = {}
    for group in overlay['conservativeGroups']:
        name = group['exclusionGroup']
        if name in declared or not isinstance(name, str) or not name:
            raise ValueError('Invalid conservative group')
        declared[name] = set(group['sourceHashes'])
        if not declared[name] <= set(by_hash):
            raise ValueError('Unknown source in conservative group')
    updated, added = copy.deepcopy(sources), 0
    for row in updated:
        linked = by_hash[row['sourceSha256']]
        original = {k:v for k,v in row.items() if k != 'athleteIds'}
        unchanged = {k:v for k,v in linked.items() if k != 'athleteIds'}
        old_ids, new_ids = set(row['athleteIds']), set(linked['athleteIds'])
        if original != unchanged or not old_ids <= new_ids:
            raise ValueError('Overlay changed nonidentity facts or removed original identity')
        delta = new_ids-old_ids
        if any(row['sourceSha256'] not in declared.get(name, set()) for name in delta):
            raise ValueError('New link lacks conservative group evidence')
        added += len(delta)
        row['athleteIds'] = sorted(new_ids)
        if delta:
            row.setdefault('provenance', []).append(copy.deepcopy(evidence))
            row['athleteIdentityScope'] = 'conservative_cross_competition_links'
    if added != overlay.get('addedSourceGroupLinks'):
        raise ValueError('Overlay link count is inconsistent')

    development = set(partitions['development'])
    previous = None
    while previous != len(development):
        previous = len(development)
        athletes = {a for s in updated if s['sourceSha256'] in development for a in s['athleteIds']}
        recordings = {s.get('originalRecordingId') for s in updated
                      if s['sourceSha256'] in development and s.get('originalRecordingId')}
        development.update(s['sourceSha256'] for s in updated
            if set(s['athleteIds']) & athletes or s.get('originalRecordingId') in recordings)
    split = dict(development=sorted(development), confirmation=[],
                 unassigned_needs_usage_audit=sorted(set(by_hash)-development))
    validate_splits(updated, split)
    return updated, split


def extend(base, overlay_path, output):
    base, overlay_path, output = map(lambda p:Path(p).resolve(), (base, overlay_path, output))
    if output.exists():
        raise ValueError('Use a new output path; preserve previous snapshots')
    base_verification = verify(base)
    checksums = json.loads((base/'SHA256SUMS.json').read_text())
    overlay = json.loads(overlay_path.read_text())
    for path, digest in overlay['inputSha256'].items():
        if sha(ROOT/path) != digest:
            raise ValueError('Identity overlay input changed: '+path)
    if sha(base/'sources.json') not in overlay['inputSha256'].values():
        raise ValueError('Identity overlay is not bound to base sources')
    read = lambda name:json.loads((base/name).read_text())
    source_document, event_document, splits, report = map(read, ['sources.json','events.json','splits.json','intake-report.json'])
    reference = {'path':str(overlay_path.relative_to(ROOT)), 'sha256':sha(overlay_path)}
    updated, partitions = apply_identity_links(source_document['sources'], event_document['events'],
                                              splits['partitions'], overlay, reference)
    input_hashes = {str((base/name).relative_to(ROOT)):digest for name,digest in checksums.items()}
    input_hashes[str((base/'SHA256SUMS.json').relative_to(ROOT))] = sha(base/'SHA256SUMS.json')
    input_hashes.update(overlay['inputSha256'])
    input_hashes[reference['path']] = reference['sha256']
    input_hashes[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
    input_hashes['tests/test_extend_axel_corpus.py'] = sha(ROOT/'tests/test_extend_axel_corpus.py')
    for path,digest in input_hashes.items():
        if path in report['inputSha256'] and report['inputSha256'][path] != digest:
            raise ValueError('Contradicting prior evidence: '+path)
    report['inputSha256'].update(input_hashes)
    old_development = set(splits['partitions']['development'])
    report['extension'] = dict(baseSnapshot=str(base.relative_to(ROOT)),
        baseManifestSha256=sha(base/'SHA256SUMS.json'), identityOverlay=reference,
        conservativeGroups=len(overlay['conservativeGroups']),
        sourceGroupLinksAdded=overlay['addedSourceGroupLinks'],
        additionalDevelopmentExclusions=sorted(set(partitions['development'])-old_development),
        baseVerification=base_verification, globalAthleteIdentityVerified=False,
        labelsChanged=False, modelFittingPerformed=False, mediaRechecked=False,
        note='Development includes linked exclusions; it does not assert each linked source was trained or viewed')
    report['summary'].update(developmentExcludedSources=len(partitions['development']),
                             unassignedNeedsUsageAudit=len(partitions['unassigned_needs_usage_audit']))
    splits.update(partitions=partitions, status='not_frozen', independenceVerified=False)
    splits['limitations'].append('Conservative competition links applied; personal cross-collection identity and re-encoded copies remain unresolved')
    payloads = {name:(base/name).read_bytes() for name in checksums}
    for name, document in [('sources.json',{**source_document,'sources':updated}),
                           ('splits.json',splits), ('intake-report.json',report)]:
        payloads[name] = (json.dumps(document, ensure_ascii=False, indent=2)+'\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.corpus-extension-', dir=output.parent) as directory:
        staging = Path(directory)/'snapshot'
        staging.mkdir()
        for name,raw in payloads.items():
            (staging/name).write_bytes(raw)
        (staging/'SHA256SUMS.json').write_text(json.dumps({name:sha(staging/name) for name in payloads}, indent=2)+'\n')
        for path,digest in report['inputSha256'].items():
            if sha(ROOT/path) != digest:
                raise ValueError('Evidence changed during extension: '+path)
        os.rename(staging, output)
    verification = verify(output)
    return dict(snapshot=str(output), addedGroups=len(overlay['conservativeGroups']),
        sourceGroupLinksAdded=overlay['addedSourceGroupLinks'],
        additionalDevelopmentExcludedSources=len(set(partitions['development'])-old_development),
        verification=verification)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--identity-links', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(extend(args.base, args.identity_links, args.output), ensure_ascii=False, indent=2))


if __name__=='__main__':
    main()
