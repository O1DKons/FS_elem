"""Append proven historical inference uses to a new corpus snapshot, without labels."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import tempfile

from axel_corpus import validate_corpus, validate_splits
from pose_cache_contract import sha
from verify_axel_corpus import verify

ROOT = Path(__file__).resolve().parents[1]


def load_usage_entries(overlay, root):
    """Bind each source to its own prior prediction record and result bytes."""
    root = Path(root).resolve()
    if type(overlay.get('schemaVersion')) is not int or overlay['schemaVersion'] != 1:
        raise ValueError('Unsupported usage overlay')
    entries, inputs, seen = [], {}, set()
    for row in overlay['entries']:
        h = row['sourceSha256']
        if not re.fullmatch('[0-9a-f]{64}', h) or h in seen or row.get('registryV5DirectUsedInDevelopment') is not False:
            raise ValueError('Invalid/duplicate historical source or prior-use assertion')
        seen.add(h)
        refs = row.get('provenance', [])
        if len(refs) != 2:
            raise ValueError('Need prediction and source-specific result evidence')
        documents = []
        for ref in refs:
            relative = Path(ref['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Evidence must stay inside the project')
            path = (root/relative).resolve()
            if not path.is_relative_to(root) or not path.is_file() or sha(path) != ref['sha256']:
                raise ValueError('Historical evidence missing or changed')
            if ref['path'] in inputs and inputs[ref['path']] != ref['sha256']:
                raise ValueError('Contradicting historical evidence')
            inputs[ref['path']] = ref['sha256']
            documents.append(json.loads(path.read_text()))
        predictions, result = documents
        matches = [r for r in predictions.get('records', []) if r.get('sha256') == h]
        if predictions.get('complete') is not True or len(matches) != 1:
            raise ValueError('Historical prediction source absent, ambiguous or incomplete')
        prediction = matches[0]
        proposal = result.get('typeProposal', {})
        if (prediction.get('id') != h or prediction.get('resultPath') != refs[1]['path']
                or result.get('sourceSha256') != h or proposal.get('video_sha256') != h
                or prediction.get('typeProposal') != proposal.get('predicted_label')
                or not predictions.get('modelSha256', {}).get('type')
                or predictions['modelSha256']['type'] != result.get('modelSha256', {}).get('type')
                or not isinstance(prediction.get('status'), str) or not prediction['status']):
            raise ValueError('Historical prediction/result identity or model disagreement')
        entries.append(dict(sourceSha256=h, personalVideoId=row['personalVideoId'],
            status=prediction['status'], typeProposal=prediction['typeProposal'],
            scope=proposal.get('scope'), provenance=copy.deepcopy(refs)))
    if not entries:
        raise ValueError('No historical source uses')
    return entries, inputs


def apply_usage(sources, events, partitions, entries, evidence):
    """Extend known-group exclusion; a prior abstention is still development use."""
    validate_corpus(sources, events)
    validate_splits(sources, partitions)
    by_hash = {s['sourceSha256']:s for s in sources}
    if set().union(*(set(v) for v in partitions.values())) != set(by_hash):
        raise ValueError('Incomplete base partition coverage')
    if partitions.get('confirmation'):
        raise ValueError('Existing confirmation needs a separate explicit split review')
    updated, seen = copy.deepcopy(sources), set()
    for entry in entries:
        h = entry['sourceSha256']
        if h not in by_hash or h in seen or by_hash[h].get('usedInDevelopment') is not False:
            raise ValueError('Unknown/duplicate source or inconsistent prior usage')
        seen.add(h)
        match = re.fullmatch(r'personal-(\d{2})', entry['personalVideoId'])
        if not match or int(match[1]) not in [m.get('personalVideoNumber') for m in by_hash[h].get('metadataObservations', [])]:
            raise ValueError('Personal video identifier does not bind the registered source')
        row = next(s for s in updated if s['sourceSha256'] == h)
        row['usedInDevelopment'] = True
        row.setdefault('historicalInferenceUses', []).append(dict(
            kind='prior_prediction_or_abstention', **copy.deepcopy({k:v for k,v in entry.items() if k != 'sourceSha256'})))
        for ref in entry['provenance']+[evidence]:
            if ref not in row['provenance']:
                row['provenance'].append(copy.deepcopy(ref))
    development = set(partitions['development']) | seen
    previous = None
    while previous != len(development):
        previous = len(development)
        athletes = {a for s in updated if s['sourceSha256'] in development for a in s['athleteIds']}
        recordings = {s['originalRecordingId'] for s in updated
                      if s['sourceSha256'] in development and s.get('originalRecordingId')}
        development.update(s['sourceSha256'] for s in updated
            if set(s['athleteIds']) & athletes or s.get('originalRecordingId') in recordings)
    split = dict(development=sorted(development), confirmation=[],
                 unassigned_needs_usage_audit=sorted(set(by_hash)-development))
    validate_splits(updated, split)
    return updated, split


def append_snapshot(base, overlay_path, output):
    base, overlay_path, output = (Path(p).resolve() for p in (base, overlay_path, output))
    if output.exists():
        raise ValueError('Use a new snapshot; previous outputs are immutable')
    base_relative = str(base.relative_to(ROOT))
    verification = verify(base)
    overlay = json.loads(overlay_path.read_text())
    if overlay.get('baseRegistry') != base_relative:
        raise ValueError('Usage overlay is not bound to this base snapshot')
    entries, inputs = load_usage_entries(overlay, ROOT)
    manifest = json.loads((base/'SHA256SUMS.json').read_text())
    inputs.update({str((base/name).relative_to(ROOT)):digest for name,digest in manifest.items()})
    ref = dict(path=str(overlay_path.relative_to(ROOT)), sha256=sha(overlay_path))
    for path in [base/'SHA256SUMS.json', overlay_path, Path(__file__),
                 ROOT/'tests/test_append_source_usage.py', ROOT/'work/registry-usage-intake-v1/design.json']:
        inputs[str(path.relative_to(ROOT))] = sha(path)
    read = lambda name:json.loads((base/name).read_text())
    source_doc, event_doc, splits, report = (read(n) for n in
        ['sources.json','events.json','splits.json','intake-report.json'])
    updated, partitions = apply_usage(source_doc['sources'], event_doc['events'], splits['partitions'], entries, ref)
    for path,digest in inputs.items():
        if path in report['inputSha256'] and report['inputSha256'][path] != digest:
            raise ValueError('Contradicting frozen evidence: '+path)
    report['inputSha256'].update(inputs)
    added = sorted(set(partitions['development'])-set(splits['partitions']['development']))
    report['usageExtension'] = dict(baseSnapshot=base_relative,
        baseManifestSha256=sha(base/'SHA256SUMS.json'), overlay=ref,
        directHistoricalSourceUses=[e['sourceSha256'] for e in entries],
        additionalDevelopmentExclusions=added, baseVerification=verification,
        labelsChanged=False, trainingUseAsserted=False, modelFittingPerformed=False,
        globalAthleteIdentityVerified=False, goal70Verified=False)
    report['summary'].update(developmentExcludedSources=len(partitions['development']),
        unassignedNeedsUsageAudit=len(partitions['unassigned_needs_usage_audit']))
    splits.update(partitions=partitions,status='not_frozen',independenceVerified=False)
    splits['limitations'].append('Prior source-specific inference/abstention is development use; it does not prove training exposure or global identity')
    payloads = {name:(base/name).read_bytes() for name in manifest}
    for name, document in [('sources.json',{**source_doc,'sources':updated}),
                           ('splits.json',splits),('intake-report.json',report)]:
        payloads[name] = (json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.usage-snapshot-',dir=output.parent) as temporary:
        staging = Path(temporary)/'snapshot';staging.mkdir()
        for name,raw in payloads.items():(staging/name).write_bytes(raw)
        (staging/'SHA256SUMS.json').write_text(json.dumps({name:sha(staging/name) for name in payloads},indent=2)+'\n')
        verify(staging)
        os.rename(staging,output)
    return dict(snapshot=str(output.relative_to(ROOT)), directHistoricalSourceUses=len(entries),
        additionalDevelopmentExcludedSources=len(added), verification=verify(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True,type=Path)
    parser.add_argument('--usage-overlay',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(append_snapshot(args.base,args.usage_overlay,args.output),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
