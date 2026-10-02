"""Replay registry integrity/evidence checks; no training, label mutation or inference."""
import argparse
import json
from pathlib import Path

from axel_corpus import validate_corpus, validate_splits
from pose_cache_contract import sha

ROOT = Path(__file__).resolve().parents[1]


def verify_files(directory):
    checksums = json.loads((directory / 'SHA256SUMS.json').read_text())
    for name, digest in checksums.items():
        if Path(name).name != name or not (directory / name).is_file():
            raise ValueError('Invalid registry manifest entry: ' + name)
        if sha(directory / name) != digest:
            raise ValueError('Registry checksum mismatch: ' + name)
    return checksums


def verify(directory, verify_media=False):
    checksums = verify_files(directory)
    required = {'sources.json', 'events.json', 'splits.json', 'intake-report.json', 'database-snapshot.json'}
    if not required <= set(checksums):
        raise ValueError('Incomplete registry manifest')
    sources = json.loads((directory / 'sources.json').read_text())['sources']
    events = json.loads((directory / 'events.json').read_text())['events']
    splits = json.loads((directory / 'splits.json').read_text())
    report = json.loads((directory / 'intake-report.json').read_text())
    validate_corpus(sources, events)
    validate_splits(sources, splits['partitions'])
    if set(splits['partitions']['development']) | set(splits['partitions']['confirmation']) | set(splits['partitions']['unassigned_needs_usage_audit']) != {s['sourceSha256'] for s in sources}:
        raise ValueError('Partition coverage incomplete')
    evidence = dict(report['inputSha256'])
    for row in sources + events:
        for ref in row.get('provenance', []):
            if ref['path'] in evidence and evidence[ref['path']] != ref['sha256']:
                raise ValueError('Contradicting evidence digests')
            evidence[ref['path']] = ref['sha256']
    for path, digest in evidence.items():
        if sha(ROOT / path) != digest:
            raise ValueError('Original evidence changed: ' + path)
    producer = {'builderMatches': sha(ROOT / 'scripts/build_axel_corpus.py') == report.get('builderSha256'),
                'validatorMatches': sha(ROOT / 'scripts/axel_corpus.py') == report.get('validatorSha256')}
    media_count = 0
    if verify_media:
        for source in sources:
            if not source['mediaHashVerified']:
                continue
            if not any((ROOT / path).is_file() and sha(ROOT / path) == source['sourceSha256']
                       for path in source['availablePaths']):
                raise ValueError('Verified source no longer matches: ' + source['sourceSha256'])
            media_count += 1
    confirmation_rejected = False
    try:
        validate_splits(sources, splits['partitions'], require_independence=True)
    except ValueError:
        confirmation_rejected = True
    if not splits['independenceVerified'] and not confirmation_rejected:
        raise ValueError('Unexpected independent-confirmation eligibility')
    return {'registrySha256': sha(directory / 'SHA256SUMS.json'), 'checkedRegistryFiles': len(checksums),
            'checkedEvidenceFiles': len(evidence), 'sources': len(sources), 'observations': len(events),
            'checkedMediaSources': media_count, 'mediaRechecked': verify_media, 'producer': producer,
            'unsafeConfirmationRejected': confirmation_rejected, 'goal70Verified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--verify-media', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.directory.resolve(), args.verify_media)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
