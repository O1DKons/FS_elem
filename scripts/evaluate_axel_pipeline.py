"""Score whole-source Axel detection/nominal outputs; never certify independence."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from import_full_program_review import _json

CLASSES = ('1A', '2A')
COUNTS = ('N', 'D', 'C', 'FP', 'unresolvedCalls', 'nominalAbstentionsOnDetectedAxels')


def normalize_legacy_axel_codes(review):
    """Known Cyrillic A spelling alias only; preserve original review/signs."""
    adapted = copy.deepcopy(review)
    for row in adapted.get('events',[]):
        code = row.get('elementCode')
        if isinstance(code,str) and re.fullmatch(r'[1-4][Аа](?:q|<|<<)?',code.strip()):
            row['elementCode'] = code.strip().replace('А','A').replace('а','A')
    return adapted


def review_playback_audit(review, source):
    """Qualify legacy rounded FPS against decoded PTS, preserving review seconds.

    This is a playback-coordinate compatibility check, not physical capture
    timing or blade-contact verification. It does not retime any annotation.
    """
    h = source.get('sourceSha256')
    if not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) or review.get('sourceSha256')!=h:
        raise ValueError('Playback review source identity mismatch')
    fps, reviewed_fps = source.get('fps'), review.get('fps')
    for value in (fps,reviewed_fps):
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('Invalid playback FPS')
    if abs(fps-reviewed_fps)<=1e-4:
        correspondence = 'matching_metadata_precision'
    elif reviewed_fps == round(fps,2):
        correspondence = 'legacy_two_decimal_rounding'
    else:
        raise ValueError('Unsupported review/decoded FPS correspondence')
    times, count = source.get('timestampsSeconds'), source.get('frameCount')
    if (type(count) is not int or count<=0 or not isinstance(times,list) or len(times)!=count
            or any(type(t) not in (int,float) or not math.isfinite(t) or t<0 for t in times)
            or times[0]!=0 or any(b<=a for a,b in zip(times,times[1:]))):
        raise ValueError('Decoded playback timestamps incomplete or invalid')
    duration = source.get('duration')
    if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0 or times[-1]>duration:
        raise ValueError('Invalid decoded source duration')
    if not isinstance(review.get('events'),list):
        raise ValueError('Review events must be a list')
    differences = []
    for event in review['events']:
        last,first = event.get('lastContactFrame'),event.get('firstContactFrame')
        if type(last) is not int or type(first) is not int or not 0<=last<first<count:
            raise ValueError('Invalid playback review contact indices')
        differences.extend(abs(times[n]-n/reviewed_fps) for n in (last,first))
    maximum = max(differences,default=0.0)
    bound = 1/min(fps,reviewed_fps)+1e-6
    if maximum>bound:
        raise ValueError('Review navigation differs from decoded contact PTS by more than one frame')
    return dict(fpsCorrespondence=correspondence,sourceFps=fps,reviewFps=reviewed_fps,
        decodedFrameCount=count,maxContactPlaybackDifferenceSeconds=maximum,
        compatibilityBoundSeconds=bound,reviewCoordinatesChanged=False,
        physicalCaptureTimebaseVerified=False,physicalContactsVerified=False)


def _interval(row, duration):
    a, b = row.get('start'), row.get('end')
    if (type(a) not in (int, float) or type(b) not in (int, float)
            or not math.isfinite(a) or not math.isfinite(b) or not 0 <= a < b <= duration):
        raise ValueError('Invalid source playback interval')
    return float(a), float(b)


def _identifier(value):
    return isinstance(value, str) and bool(value.strip())


def _validate(sources, predictions):
    if not isinstance(sources, list) or not sources or not isinstance(predictions, list):
        raise ValueError('Need all reviewed sources and a prediction list, including empty outputs')
    by_hash, ids = {}, set()
    for source in sources:
        if not isinstance(source, dict) or not _identifier(source.get('id')) or source['id'] in ids:
            raise ValueError('Invalid or duplicate source identifier')
        ids.add(source['id'])
        h = source.get('sourceSha256')
        if not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) or h in by_hash:
            raise ValueError('Invalid or duplicate source SHA256')
        by_hash[h] = source
        duration = source.get('durationSeconds')
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid source duration')
        if (source.get('coverageReviewed') is not True or source.get('inferenceScope') != 'whole_source'
                or source.get('inferenceStatus') not in ('completed', 'failed')
                or source.get('domain') not in ('personal', 'full_program') or source.get('qaOnly') is True):
            raise ValueError('Need non-QA whole-source inference and explicit full review')
        events = source.get('events')
        if not isinstance(events, list):
            raise ValueError('Expert events must be a list')
        event_ids, known = set(), []
        for event in events:
            if not isinstance(event, dict) or not _identifier(event.get('id')) or event['id'] in event_ids:
                raise ValueError('Invalid or duplicate expert event')
            event_ids.add(event['id'])
            a, b = _interval(event, duration)
            kind, nominal = event.get('eventClass'), event.get('nominal')
            if (kind not in ('axel', 'other_jump', 'uncertain')
                    or event.get('boundaryStatus') != 'expert_playback_evaluation'
                    or (kind == 'axel' and nominal not in CLASSES)
                    or (kind != 'axel' and nominal is not None)):
                raise ValueError('Unsupported/quarantined expert observation')
            if kind != 'uncertain':
                known.append((a, b))
        known.sort()
        if any(current[0] < previous[1] for previous, current in zip(known, known[1:])):
            raise ValueError('Confirmed expert flight interiors overlap')
    seen = set()
    for row in predictions:
        if not isinstance(row, dict) or row.get('sourceSha256') not in by_hash or not _identifier(row.get('id')):
            raise ValueError('Invalid prediction or unknown source')
        key = row['sourceSha256'], row['id']
        if key in seen:
            raise ValueError('Duplicate prediction identifier')
        seen.add(key)
        source = by_hash[row['sourceSha256']]
        _interval(row, source['durationSeconds'])
        if (source['inferenceStatus'] == 'failed' or row.get('family') not in ('axel', 'other', None)
                or row.get('nominal') not in (None, '1A', '2A', '3A', '4A')
                or (row.get('family') != 'axel' and row.get('nominal') is not None)):
            raise ValueError('Unsupported prediction or outputs claimed from failed inference')


def _rates(counts, duration):
    n, d, c, fp, unresolved = (counts[k] for k in ('N', 'D', 'C', 'FP', 'unresolvedCalls'))
    return {**counts, 'jointRecall':c/n if n else None, 'detectionRecall':d/n if n else None,
            'precision':d/(d+fp) if d+fp else None,
            'precisionWithUnresolvedAsFalse':d/(d+fp+unresolved) if d+fp+unresolved else None,
            'conditionalNominalAccuracy':c/d if d else None,
            'falseCallsPerMinute':fp*60/duration, 'durationSeconds':duration}


def _source_score(source, predictions):
    events = sorted(source['events'], key=lambda e:(e['start'], e['id']))
    calls = sorted([p for p in predictions if p['family']=='axel'], key=lambda p:(p['start'], p['id']))
    known = [i for i, e in enumerate(events) if e['eventClass'] != 'uncertain']
    uncertain = [i for i, e in enumerate(events) if e['eventClass'] == 'uncertain']
    centers = [(e['start']+e['end'])/2 for e in events]
    edges, overlaps = {}, {}
    for i, call in enumerate(calls):
        eligible = []
        for j in known:
            event = events[j]
            intersection = max(0.0, min(call['end'], event['end'])-max(call['start'], event['start']))
            union = call['end']-call['start']+event['end']-event['start']-intersection
            iou = intersection/union
            if call['start'] <= centers[j] <= call['end'] and iou >= .3:
                eligible.append(j); overlaps[i, j] = iou
        edges[i] = sorted(eligible, key=lambda j:(abs((call['start']+call['end'])/2-centers[j]), events[j]['id']))
    assigned = {}

    def assign(index, visited):
        for j in edges[index]:
            if j in visited:
                continue
            visited.add(j)
            previous = assigned.get(j)
            if previous is None or assign(previous, visited):
                assigned[j] = index
                return True
        return False

    for i in range(len(calls)):
        assign(i, set())
    matched = {i:j for j,i in assigned.items()}
    unresolved = {i for i, call in enumerate(calls) if i not in matched and not edges[i]
                  and any(call['start'] <= centers[j] <= call['end'] for j in uncertain)}
    detected = [j for j,i in assigned.items() if events[j]['eventClass']=='axel']
    correct = [j for j in detected if calls[assigned[j]]['nominal']==events[j]['nominal']]
    false_ids = [call['id'] for i,call in enumerate(calls)
                 if i not in unresolved and (i not in matched or events[matched[i]]['eventClass']=='other_jump')]
    counts = dict(N=sum(e['eventClass']=='axel' for e in events), D=len(detected), C=len(correct),
        FP=len(false_ids), unresolvedCalls=len(unresolved),
        nominalAbstentionsOnDetectedAxels=sum(calls[assigned[j]]['nominal'] is None for j in detected),
        byClass={label:dict(N=sum(e['eventClass']=='axel' and e['nominal']==label for e in events),
            D=sum(events[j]['nominal']==label for j in detected),
            C=sum(events[j]['nominal']==label for j in correct)) for label in CLASSES})
    matches = [dict(predictionId=calls[i]['id'], eventId=events[j]['id'],
        eventClass=events[j]['eventClass'], intervalIoU=overlaps[i,j],
        predictedNominal=calls[i]['nominal'], expertNominal=events[j]['nominal'],
        nominalCorrect=events[j]['eventClass']=='axel' and calls[i]['nominal']==events[j]['nominal'])
        for i,j in sorted(matched.items())]
    return {**_rates(counts,source['durationSeconds']), 'sourceId':source['id'],
        'sourceSha256':source['sourceSha256'], 'domain':source['domain'],
        'inferenceStatus':source['inferenceStatus'], 'automaticCandidates':len(predictions),
        'axelCalls':len(calls), 'expertUncertainEvents':len(uncertain), 'matches':matches,
        'missedAxelIds':[e['id'] for j,e in enumerate(events) if e['eventClass']=='axel' and j not in assigned],
        'falseAxelCallIds':false_ids, 'unresolvedCallIds':[calls[i]['id'] for i in sorted(unresolved)]}


def _aggregate(rows):
    counts = {key:sum(row[key] for row in rows) for key in COUNTS}
    counts['byClass'] = {label:{k:sum(r['byClass'][label][k] for r in rows)
                              for k in ('N','D','C')} for label in CLASSES}
    counts['sourceCount'] = len(rows)
    return _rates(counts, sum(row['durationSeconds'] for row in rows))


def _gate(metrics):
    reasons = []
    if metrics['jointRecall'] is None or metrics['jointRecall'] < .7:
        reasons.append('joint_recall_below_70_or_no_axels')
    if metrics['precisionWithUnresolvedAsFalse'] is None or metrics['precisionWithUnresolvedAsFalse'] < .7:
        reasons.append('conservative_precision_below_70_or_no_calls')
    for label in CLASSES:
        row = metrics['byClass'][label]
        if not row['N'] or row['C']/row['N'] < .7:
            reasons.append(label+'_joint_recall_below_70_or_absent')
    return dict(passed=not reasons, reasons=reasons,
                scope='Numerical development check only; not independent goal confirmation')


def evaluate(sources, predictions):
    """All reviewed sources are denominators, even when the pipeline failed."""
    _validate(sources, predictions)
    rows = [_source_score(source, [p for p in predictions if p['sourceSha256']==source['sourceSha256']])
            for source in sources]
    domains = {domain:_aggregate([row for row in rows if row['domain']==domain])
               for domain in sorted({row['domain'] for row in rows})}
    gates = {domain:_gate(metrics) for domain,metrics in domains.items()}
    return dict(schemaVersion=1, sources=rows, domains=domains, numericalGates=gates,
        pooledDiagnostic=_aggregate(rows), allDomainsNumericalGatePassed=all(g['passed'] for g in gates.values()),
        failedSourceIds=[s['id'] for s in sources if s['inferenceStatus']=='failed'],
        matcher='maximum one-to-one, class/nominal-neutral, midpoint inside and temporal IoU>=0.3',
        independentConfirmationVerified=False, goal70Verified=False, underrotation=None,
        physicalAirborneTurns=None, coldRuntimeSeconds=None,
        limitations=['Development scores do not prove a closed unseen-athlete test',
            'Nominal labels are not measured airborne revolutions or underrotation',
            'Pooled counts are diagnostic; each acquisition domain and nominal is reported separately',
            'Source review/whole-scan assertions require separate provenance and independence audits',
            'Unknown expert events are listed; numerical gate uses precision counting unresolved calls as false'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refusing to overwrite evaluation')
    raw = args.input.read_bytes(); document = _json(raw)
    if not isinstance(document,dict) or type(document.get('schemaVersion')) is not int or document['schemaVersion']!=1:
        raise ValueError('Input schemaVersion must be integer1')
    if document.get('qaOnly') is True:
        raise ValueError('QA-only input cannot become a model evaluation')
    result = evaluate(document['sources'],document['predictions'])
    result['inputSha256'] = hashlib.sha256(raw).hexdigest()
    result['evaluatorSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps(dict(domains=result['domains'],goal70Verified=False),ensure_ascii=False))


if __name__=='__main__':main()
