"""Overlay prior exact-name exclusion evidence; never certify global identities."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def competition_links(sources, library, overlaps):
    augmented = copy.deepcopy(sources)
    groups = []
    for row in overlaps:
        identity = row['conservativeExclusionGroup']
        old_ids = {'comp-'+str(n) for n in row['oldCompetitionStartNumbers']}
        new_ids = {p['programId'] for p in row['newPrograms']}
        new_hashes = {p['sourceSha256'] for p in library
                      if p.get('matchStatus')=='matched' and p.get('programId') in new_ids}
        linked = []
        for source in augmented:
            old_match = any(m.get('videoId') in old_ids for m in source.get('metadataObservations', []))
            if old_match or source['sourceSha256'] in new_hashes:
                source['athleteIds'] = sorted(set(source.get('athleteIds', [])) | {identity})
                linked.append(source['sourceSha256'])
        groups.append(dict(exclusionGroup=identity, sourceHashes=sorted(linked),
                           programIds=sorted(new_ids), legacyVideoIds=sorted(old_ids),
                           evidence='Existing exact normalized given-name/surname audit and matched program/source bindings',
                           identityQualification='Conservative exclusion, not global identity verification'))
    return augmented, groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [ROOT/'data/axel-corpus-v3/sources.json', ROOT/'data/axel-corpus-v3/program-library.json',
             ROOT/'work/protocol-localization-v1/athlete-overlap-audit.json', Path(__file__),
             ROOT/'tests/test_axel_competition_links.py']
    inputs = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    read = lambda p:json.loads(p.read_text())
    original = read(paths[0])['sources']
    sources, groups = competition_links(original, read(paths[1])['records'], read(paths[2])['exactFullNameOverlaps'])
    result = dict(schemaVersion=1, sources=sources, conservativeGroups=groups, inputSha256=inputs,
                  addedSourceGroupLinks=sum(len(a['athleteIds'])-len(b['athleteIds']) for a,b in zip(sources,original)),
                  replacesRegistry=False, globallyVerifiedIdentity=False,
                  scope='Additional exclusion overlay for v3; old source labels and immutable snapshots remain unchanged')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(dict(groups=len(groups), sourceGroupLinksAdded=result['addedSourceGroupLinks']))


if __name__=='__main__':
    main()
