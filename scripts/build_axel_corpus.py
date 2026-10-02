"""Consolidate existing evidence, preserving its scope; never train or relabel inputs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from axel_corpus import validate_corpus,validate_splits
from pose_cache_contract import sha
ROOT=Path(__file__).resolve().parents[1]


def nominal(code):
    m=re.fullmatch(r'([1-4]A)(?:q|<|<<)?',code or '')
    return m.group(1) if m else None


def legacy_contact_observation(event, source_hash, fps, provenance):
    a, b = event['lastContactFrame'], event['firstContactFrame']
    if (type(a) is not int or type(b) is not int or not 0 <= a < b
            or type(fps) not in [int, float] or not math.isfinite(fps) or fps <= 0):
        raise ValueError('Invalid legacy contacts/timebase')
    code = event.get('elementCode')
    return {'eventId': 'legacy-contact:' + event['id'], 'originalEventId': event['id'],
            'sourceSha256': source_hash, 'labelScope': 'protocol_supported_contact_observation',
            'protocolCode': code, 'protocolNominalHint': nominal(code),
            'reportedEventClass': event.get('eventClass'),
            'lastContactFrame': a, 'firstContactFrame': b,
            'startSeconds': a / fps, 'endSeconds': b / fps,
            'timebase': 'legacy source frame indices / recorded FPS; not a new expert review',
            'provenance': provenance, 'modelTrainingEligible': False}


def confirmed_report_observation(row, card, source_hash, provenance):
    component = row['confirmedReportComponent']
    if (row['id'] != card['id'] or card['kind'] != 'jump'
            or component != card['protocolComponent']):
        raise ValueError('Confirmed card/manifest mismatch')
    code = component['code']
    family = 'axel' if component.get('jumpFamily') == 'A' else 'other'
    return {'eventId': 'confirmed-card:' + row['id'], 'originalEventId': row['id'],
            'sourceSha256': source_hash, 'labelScope': 'confirmed_report_card',
            'family': family, 'nominal': nominal(code) if family == 'axel' else None,
            'elementCode': code, 'reportedSign': component.get('rotationSign'),
            'measuredUnderrotation': None, 'physicalAirborneTurns': None,
            'startSeconds': card['review']['start'], 'endSeconds': card['review']['end'],
            'reviewComplete': False, 'boundaryStatus': 'report_display_approximation',
            'provenance': provenance, 'modelTrainingEligible': True,
            'eligibleTrainingTargets': ['family', 'nominal'] if family == 'axel' else ['family']}


def contact_conflicts(events):
    groups = defaultdict(list)
    for event in events:
        if event.get('lastContactFrame') is not None and event.get('firstContactFrame') is not None:
            groups[(event['sourceSha256'], event['lastContactFrame'])].append(event)
    return [{'kind': 'different_landings_for_same_takeoff', 'sourceSha256': h,
             'lastContactFrame': a, 'eventIds': [e['eventId'] for e in rows],
             'firstContactFrames': sorted({e['firstContactFrame'] for e in rows}),
             'resolution': 'Unresolved observations preserved; no automatic overwrite'}
            for (h, a), rows in sorted(groups.items())
            if len({e['firstContactFrame'] for e in rows}) > 1]


def build(output,verify_media=False,include_program_library=False):
    if output.exists() and any(output.iterdir()):raise ValueError('Use a new output directory; preserve prior registry')
    sources={};events=[];inputs={};unresolved=[];snapshot={};library=[]
    def relative(path):
        path=Path(path).resolve()
        try:return str(path.relative_to(ROOT))
        except ValueError:return str(path)
    def load(path):
        path=Path(path);path=path if path.is_absolute() else ROOT/path
        inputs[relative(path)]=sha(path);return json.loads(path.read_text())
    def evidence(path):
        key=relative(path);return [{'path':key,'sha256':inputs[key]}]
    def add_source(h,path=None,collection=None,athlete=None,reference=None,metadata=None):
        if not re.fullmatch(r'[0-9a-f]{64}',h or ''):raise ValueError('Missing valid source digest')
        s=sources.setdefault(h,{'sourceSha256':h,'paths':[],'collections':[],'athleteIds':[],'athleteLabels':[],
                               'originalRecordingId':'exact-file:'+h,'recordingGroupVerified':False,
                               'recordingIdentityStatus':'exact_file_only','athleteIdentityVerified':False,
                               'completeReviews':[],'usedInDevelopment':False,'provenance':[],'metadataObservations':[]})
        if path and relative(path) not in s['paths']:s['paths'].append(relative(path))
        if collection and collection not in s['collections']:s['collections'].append(collection)
        if athlete:
            label=' '.join(athlete.split());ident=collection+':'+hashlib.sha256(label.casefold().encode()).hexdigest()[:20]
            if ident not in s['athleteIds']:s['athleteIds'].append(ident)
            if label not in s['athleteLabels']:s['athleteLabels'].append(label)
        if reference:
            for ref in reference:
                if ref not in s['provenance']:s['provenance'].append(ref)
        if metadata:s['metadataObservations'].append(metadata)
        return s
    def add_event(e):
        e.setdefault('nominal',None);e.setdefault('family',None);e.setdefault('reviewComplete',False)
        e.setdefault('startSeconds',None);e.setdefault('endSeconds',None)
        events.append(e)
        if e['family'] is not None:sources[e['sourceSha256']]['usedInDevelopment']=True

    # Read a coherent projection of the live database; no copying active DB/WAL.
    db=sqlite3.connect('file:'+str(ROOT/'data/live/fs-elem.sqlite')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        db.execute('BEGIN')
        for table in ['videos','attempts','expert_labels']:
            snapshot[table]=[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')]
    finally:db.rollback();db.close()
    raw_snapshot=json.dumps(snapshot,ensure_ascii=False,indent=2).encode();snapshot_hash=hashlib.sha256(raw_snapshot).hexdigest()
    snapshot_ref=[{'path':relative(output/'database-snapshot.json'),'sha256':snapshot_hash}]
    videos={}
    for row in snapshot['videos']:
        v=json.loads(row['payload']);videos[row['id']]=v
        add_source(v['sha256'],ROOT/'data/live'/row['media_path'],v.get('collection','legacy'),reference=snapshot_ref,
                   metadata={'videoId':row['id'],'title':v.get('title'),'duration':v.get('duration'),'fps':v.get('fps')})
    for row in snapshot['attempts']:
        v=videos[row['video_id']];payload=json.loads(row['payload']);confirmed=payload.get('boundaryImport',{}).get('confirmedFrames',{})
        a,b=confirmed.get('lastContact'),confirmed.get('firstContact');contacts=type(a) is int and type(b) is int and 0<=a<b
        start,end=payload.get('start'),payload.get('end')
        if contacts and v.get('fps',0)>0:start,end=a/v['fps'],b/v['fps']
        if start is None or end is None or not 0<=start<end:start=end=None
        add_event({'eventId':'editor:'+row['id'],'originalEventId':row['id'],'sourceSha256':v['sha256'],
                   'labelScope':'manual_contact' if contacts else 'protocol_only','startSeconds':start,'endSeconds':end,
                   'lastContactFrame':a if contacts else None,'firstContactFrame':b if contacts else None,
                   'protocolCode':payload.get('protocolCode'),'protocolNominalHint':nominal(payload.get('protocolCode')),
                   'provenance':snapshot_ref,'timebase':'editor metadata; no conversion asserted beyond stored FPS',
                   'modelTrainingEligible':False})
    for row in snapshot['expert_labels']:
        v=videos[row['video_id']];payload=json.loads(row['payload']);n=nominal(payload.get('element'))
        add_event({'eventId':'legacy-video-label:'+str(row['id']),'sourceSha256':v['sha256'],
                   'labelScope':'video_identity_only','family':'axel' if n else None,'nominal':n,
                   'elementCode':payload.get('element'),'provenance':snapshot_ref,'modelTrainingEligible':False})

    # Personal source and user athlete mapping. Names are qualified by collection.
    personal_path=ROOT/'data/axel-demo-v1/personal-video-review/data.json';personal=load(personal_path)
    mapping_path=ROOT/'work/personal-validation-intake/user-athletes-1-51.json';mapping=load(mapping_path)
    if personal['datasetSha256']!=mapping['datasetSha256']:raise ValueError('Personal athlete map/source mismatch')
    groups={n:g['athleteId'] for g in mapping['groups'] for n in g['videoNumbers']};personal_by_number={}
    for item in personal['items']:
        number=int(Path(item['file']).stem);personal_by_number[number]=item
        add_source(item['sha256'],personal_path.parent/item['file'],'personal',groups.get(number),evidence(mapping_path),
                   {'personalVideoNumber':number})
    family_path=ROOT/'work/personal-candidate-feedback-v1/family-development-intake.json';family=load(family_path)
    for row in family['records']:
        h=row['sourceSha256'];add_source(h,collection='personal',athlete=row['athlete'],reference=evidence(family_path))
        add_event({'eventId':f"personal-candidate:{h}:{row['candidate']}",'sourceSha256':h,'family':row['family'],
                   'nominal':nominal(row.get('nominal')),'startSeconds':row['startSeconds'],'endSeconds':row['endSeconds'],
                   'labelScope':'candidate_family','boundaryStatus':'automatic_candidate','provenance':evidence(family_path),
                   'modelTrainingEligible':True})
    for row in family['quarantined']:
        unresolved.append({'kind':'quarantined_personal_candidate',**row})
        item=personal_by_number.get(row['video'])
        if item:sources[item['sha256']]['usedInDevelopment']=True
    near_path=ROOT/'work/personal-candidate-family-artifacts-v1/protocol.json';near=load(near_path)
    pair=[personal_by_number[n]['sha256'] for n in [7,15]]
    if near['excludedNearDuplicate'] not in pair:raise ValueError('Near-duplicate mapping changed')
    for h in pair:
        sources[h]['originalRecordingId']='conservative-near-duplicate:'+min(pair)
        sources[h]['recordingIdentityStatus']='research_near_duplicate_group'
        sources[h]['provenance'].extend(evidence(near_path))
    if 18 in personal_by_number:
        sources[personal_by_number[18]['sha256']]['recordingIdentityStatus']='duplicate_association_pending'

    intake_path=ROOT/'work/personal-eight-events-v1/intake.json';intake=load(intake_path)
    for record in intake['records']:
        base=ROOT/'work/personal-event-intake-v1/imports'/record['reviewSha256'];raw_path=base/'review.json';validated_path=base/'validated.json'
        raw=load(raw_path);v=load(validated_path)
        if inputs[relative(raw_path)]!=record['reviewSha256']:raise ValueError('Personal original review hash mismatch')
        if v['videoId']!=v['originalSourceSha256']:raise ValueError('Unverified personal review-media conversion')
        h=v['videoId'];complete=raw.get('coverageReviewed') is True
        if complete:sources[h]['completeReviews'].append(evidence(raw_path)[0])
        for e in v['events']:
            f='axel' if e['eventClass']=='axel' else 'other' if e['eventClass']=='other_jump' else None
            add_event({'eventId':'personal-review:'+e['id'],'originalEventId':e['id'],'sourceSha256':h,
                       'family':f,'nominal':nominal(e.get('elementCode')) if f=='axel' else None,
                       'elementCode':e.get('elementCode'),'startSeconds':e['start'],'endSeconds':e['end'],
                       'labelScope':'full_review' if complete else 'selected_event_review','reviewComplete':complete,
                       'timebase':v['timebase'],'provenance':evidence(raw_path)+evidence(validated_path),'modelTrainingEligible':f is not None})

    spec_path=ROOT/'work/full-program-feet-flight-v1/protocol.json';spec=load(spec_path)
    for record in spec['records']:
        h=record['sourceSha256'];s=add_source(h,ROOT/record['sourcePath'],'competition',record['athlete'],evidence(spec_path),
                                           {'sourceFps':record['sourceFps'],'duration':record['duration']})
        s['usedInDevelopment']=True
        if not record['exhaustive']:
            for e in record['contactEvents']:
                add_event(legacy_contact_observation(e,h,record['sourceFps'],evidence(spec_path)))
            continue
        path=ROOT/record['reviewPath'];review=load(path)
        if review['sourceSha256']!=h or review['coverageReviewed'] is not True:raise ValueError('Full review scope/source mismatch')
        s['completeReviews'].append(evidence(path)[0])
        for e in review['events']:
            a,b=e['lastContactFrame'],e['firstContactFrame']
            if type(a) is not int or type(b) is not int or not 0<=a<b:raise ValueError('Invalid full review contacts')
            f='axel' if e['eventClass']=='axel' else 'other' if e['eventClass']=='other_jump' else None
            add_event({'eventId':'full-review:'+e['id'],'originalEventId':e['id'],'sourceSha256':h,'family':f,
                       'nominal':nominal(e.get('elementCode')) if f=='axel' else None,'elementCode':e.get('elementCode'),
                       'startSeconds':a/review['fps'],'endSeconds':b/review['fps'],'lastContactFrame':a,'firstContactFrame':b,
                       'labelScope':'full_review','reviewComplete':True,'timebase':'source frame indices / review FPS',
                       'provenance':evidence(path),'modelTrainingEligible':f is not None})

    corpus_path=ROOT/'work/eight-source-reviewed-family-v1/corpus.json';corpus=load(corpus_path)
    for row in corpus['records']:
        pose_path=ROOT/row['densePose'];pose=load(pose_path);h=row['sourceSha256']
        if pose['source']['sourceSha256']!=h:raise ValueError('Competition candidate/source mismatch')
        add_source(h,pose['source']['sourcePath'],'competition',row['athleteGroup'],evidence(corpus_path),
                   {'programId':row['programId'],'sourceFps':pose['source']['fps']})
        expert=ROOT/row['expertFile'];load(expert)
        add_event({'eventId':'competition-candidate:'+row['candidateId'],'originalEventId':row['candidateId'],'sourceSha256':h,
                   'family':row['family'],'nominal':nominal(row.get('nominal')),'labelScope':'candidate_family',
                   'startSeconds':row['automaticInterval']['start'],'endSeconds':row['automaticInterval']['end'],
                   'boundaryStatus':'automatic_candidate','provenance':evidence(corpus_path)+evidence(expert),'modelTrainingEligible':True})
    unresolved.extend({'kind':'confirmed_report_component_not_localized_in_original_candidates',**x} for x in corpus['unproposedConfirmedJumps'])
    six_paths=sorted((ROOT/'work/six-axel-contact-review-v1/expert-reviews').glob('*/receipt.json'))
    for path in six_paths:
        receipt=load(path);original=path.parent/'original.json';load(original)
        if inputs[relative(original)]!=receipt['reviewSha256']:raise ValueError('Six-contact export mismatch')
        for row in receipt['records']:
            h=row['sourceSha256'];add_source(h,collection='competition',athlete=row['athlete'],reference=evidence(path))
            a,b=row['lastContactFrame'],row['firstContactFrame'];ready=row['readyForContactTraining']
            add_event({'eventId':'selected-contacts:'+row['id'],'originalEventId':row['id'],'sourceSha256':h,'family':'axel',
                       'nominal':row['nominal'],'labelScope':'selected_contact_review',
                       'lastContactFrame':a,'firstContactFrame':b,'startSeconds':a/row['fps'] if ready else None,
                       'endSeconds':b/row['fps'] if ready else None,'timebase':'source frame indices / reviewed FPS',
                       'provenance':evidence(original)+evidence(path),'modelTrainingEligible':ready})

    # User confirmations of protocol-assisted cards retain approximate boundaries and scope.
    extended_base=ROOT/'work/prospective-family-dense-two-source-v1'
    extended_manifest_path=extended_base/'extended-report-manifest.json';extended_manifest=load(extended_manifest_path)
    cards={r['id']:r for r in extended_manifest['records'] if r['kind']=='jump'}
    selection_path=extended_base/'selection.json';selection=load(selection_path)
    programs={r['programId']:r for r in selection['records']}
    for path in sorted((extended_base/'expert-reviews').glob('*/receipt.json')):
        receipt=load(path);raw_path=path.parent/'extended-two-programs-review.json';raw=load(raw_path)
        if inputs[relative(raw_path)]!=receipt['sourceSha256'] or raw['reviewId']!=receipt['reviewId']:
            raise ValueError('Extended original review/receipt mismatch')
        for row in receipt['records']:
            card=cards[row['id']];program=programs[card['programId']];h=program['sourceSha256']
            add_source(h,program['path'],'competition',program['athlete'],evidence(selection_path))
            add_event(confirmed_report_observation(row,card,h,evidence(raw_path)+evidence(path)+evidence(extended_manifest_path)))

    # Audit current media in the entire 178-program library, without running any model.
    if include_program_library:
        matches_path=ROOT/'data/new-programs-protocols-v1/video-matches.json';matches=load(matches_path)
        inventory_path=ROOT/'data/new-programs-protocols-v1/axel-inventory.json';inventory=load(inventory_path)
        programs_path=ROOT/'data/new-programs-protocols-v1/programs.json';load(programs_path)
        if inputs[relative(programs_path)]!=matches['programsSha256'] or matches['programsSha256']!=inventory['programsSha256']:
            raise ValueError('Protocol inventory/match source mismatch')
        by_path={}
        for match in matches['matches']:
            row=match['video'];path=Path(row['path']);observed={'path':relative(path),'programId':match['programId'],
                'matchStatus':match['status'],'recordedSize':row['fileSizeBytes'],'recordedMtimeNs':row['fileMtimeNs']}
            if not path.is_file():
                observed['status']='missing';library.append(observed)
                unresolved.append({'kind':'program_library_media_missing',**observed});continue
            before=path.stat();h=sha(path);after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Media changed while hashing: '+str(path))
            observed.update(sourceSha256=h,currentSize=after.st_size,currentMtimeNs=after.st_mtime_ns,
                            status='content_hashed',metadataMatches=after.st_size==row['fileSizeBytes'] and after.st_mtime_ns==row['fileMtimeNs'])
            library.append(observed);by_path[str(path)]=observed
            s=add_source(h,path,'competition',row['athleteName'],evidence(matches_path),
                         {'programId':match['programId'],'category':row['categoryKey'],'segment':row['segment'],
                          'protocolMatchStatus':match['status'],'identityScope':'filename metadata, collection only'})
            s['contentHashVerifiedDuringLibraryIntake']=True
            if not observed['metadataMatches']:unresolved.append({'kind':'program_library_metadata_changed',**observed})
        for index,row in enumerate(inventory['axels']):
            observed=by_path.get(row['video']['path'])
            if not observed or not observed['metadataMatches']:
                unresolved.append({'kind':'protocol_component_media_unavailable_or_changed','programId':row['programId'],
                                   'sequence':row['sequence'],'componentIndex':row['componentIndex']});continue
            add_event({'eventId':f"library-protocol:{row['programId']}:{row['sequence']}:{row['componentIndex']}:{index}",
                       'sourceSha256':observed['sourceSha256'],'labelScope':'protocol_only',
                       'protocolCode':row['componentCode'],'protocolNominalHint':row['nominalAxel'],
                       'protocolInvalid':row['invalid'],'protocolSource':row['source'],
                       'boundaryStatus':'unlocalized','provenance':evidence(inventory_path)+evidence(matches_path),
                       'modelTrainingEligible':False})

    # Training provenance is an explicit development-use record, never proof of visual truth.
    training_path=ROOT/'configs/axel-baseline-training-v1.json';training=load(training_path)
    for role,model in training['models'].items():
        for row in model['trainingSources']:
            h=row['sourceSha256'];collection='competition' if role=='nominal' else 'personal'
            s=add_source(h,collection=collection,athlete=row['athleteLabel'],reference=evidence(training_path))
            use={'role':role,'modelSha256':model['modelSha256']}
            if use not in s.setdefault('trainingUses',[]):s['trainingUses'].append(use)
            s['usedInDevelopment']=True
    unresolved.extend(contact_conflicts(events))

    # All observed sources remain development; unassigned is not an unused test set.
    development={h for h,s in sources.items() if s['usedInDevelopment']}
    changed=True
    while changed:
        old=len(development);athletes={a for h in development for a in sources[h]['athleteIds']};recordings={sources[h]['originalRecordingId'] for h in development}
        development.update(h for h,s in sources.items() if set(s['athleteIds'])&athletes or s['originalRecordingId'] in recordings)
        changed=len(development)!=old
    label_sources={e['sourceSha256'] for e in events if e['family'] is not None}
    for h,s in sources.items():
        s['athleteId']=s['athleteIds'][0] if s['athleteIds'] else None
        s['athleteIdentityScope']='collection_only' if s['athleteIds'] else 'unknown'
        s['availablePaths']=[p for p in s['paths'] if (ROOT/p).is_file()]
        s['mediaHashVerified']=s.get('contentHashVerifiedDuringLibraryIntake',False)
        if verify_media and h in label_sources:
            matches=[p for p in s['availablePaths'] if sha(ROOT/p)==h]
            s['verifiedPaths']=matches;s['mediaHashVerified']=bool(matches)
            if not matches:unresolved.append({'kind':'labelled_media_not_verified','sourceSha256':h,'paths':s['paths']})
    source_rows=sorted(sources.values(),key=lambda s:s['sourceSha256'])
    partitions={'development':sorted(development),'confirmation':[],'unassigned_needs_usage_audit':sorted(set(sources)-development)}
    validate_corpus(source_rows,events);validate_splits(source_rows,partitions)
    summary={'sourceFiles':len(sources),'labelObservations':len(events),'scopes':dict(Counter(e['labelScope'] for e in events)),
             'fullyReviewedSourceFiles':sum(bool(s['completeReviews']) for s in sources.values()),
             'fullyReviewedAxelsByNominal':dict(Counter(e['nominal'] or 'unknown' for e in events if e['reviewComplete'] and e['family']=='axel')),
             'selectedLabelSources':len(label_sources),'verifiedMediaSources':sum(s['mediaHashVerified'] for s in sources.values()),
             'verifiedExpertLabelledMediaSources':sum(s['mediaHashVerified'] for h,s in sources.items() if h in label_sources),
             'programLibraryFiles':len(library),'hashedProgramLibraryFiles':sum(r['status']=='content_hashed' for r in library),
             'unresolvedIssues':len(unresolved),'frozenConfirmationSources':0,'goal70Verified':False}
    for path,digest in inputs.items():
        if sha(ROOT/path)!=digest:raise ValueError('Input evidence changed during build: '+path)
    output.mkdir(parents=True,exist_ok=True)
    (output/'database-snapshot.json').write_bytes(raw_snapshot)
    documents={'sources.json':{'schemaVersion':1,'sources':source_rows},'events.json':{'schemaVersion':1,'events':events},
               'splits.json':{'schemaVersion':1,'status':'not_frozen','partitions':partitions,'independenceVerified':False,
                              'limitations':['No confirmation set yet; existing reviewed sources are development','Unassigned sources require prior-usage audit','Cross-collection athlete and re-encoded-original links unresolved']},
               'intake-report.json':{'summary':summary,'unresolved':unresolved,'inputSha256':inputs,
                                    'builderSha256':sha(Path(__file__)),'validatorSha256':sha(ROOT/'scripts/axel_corpus.py'),
                                    'scope':'Evidence observations are not deduplicated independent events; protocol hints are not expert truths.'}}
    if library:documents['program-library.json']={'schemaVersion':1,'records':library,'scope':'Content identity and protocol metadata, no new expert temporal labels or unused-test proof'}
    for name,doc in documents.items():
        with (output/name).open('x') as stream:json.dump(doc,stream,ensure_ascii=False,indent=2)
    checksums={p.name:sha(p) for p in output.iterdir() if p.is_file()}
    (output/'SHA256SUMS.json').write_text(json.dumps(checksums,indent=2));return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'data/axel-corpus-v1');p.add_argument('--verify-reviewed-media',action='store_true');p.add_argument('--include-program-library',action='store_true');a=p.parse_args()
    print(json.dumps(build(a.output.resolve(),a.verify_reviewed_media,a.include_program_library),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
