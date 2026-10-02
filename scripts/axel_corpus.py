"""Corpus integrity and split guards. No training or inference."""
import math
import re

SCOPES={'full_review','selected_event_review','selected_contact_review','candidate_family','manual_contact',
        'protocol_only','video_identity_only','protocol_supported_contact_observation','confirmed_report_card'}


def validate_corpus(sources,events):
    ids=[s['sourceSha256'] for s in sources]
    if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[0-9a-f]{64}',s) for s in ids):raise ValueError('Invalid/duplicate source hashes')
    event_ids=set()
    for event in events:
        eid=event['eventId'];scope=event.get('labelScope')
        if eid in event_ids:raise ValueError('Duplicate observation ID')
        event_ids.add(eid)
        if event['sourceSha256'] not in ids:raise ValueError('Unknown event source')
        if scope not in SCOPES or not event.get('provenance'):raise ValueError('Missing/unsupported label provenance')
        for ref in event['provenance']:
            if (not isinstance(ref,dict) or not isinstance(ref.get('path'),str) or not ref['path']
                    or not re.fullmatch(r'[0-9a-f]{64}',ref.get('sha256',''))):
                raise ValueError('Invalid evidence path/digest')
        if event.get('reviewComplete') and scope!='full_review':raise ValueError('Partial labels cannot imply complete review')
        family,nominal=event.get('family'),event.get('nominal')
        if family not in [None,'axel','other']:raise ValueError('Invalid family')
        if nominal not in [None,'1A','2A','3A','4A']:raise ValueError('Invalid Axel nominal')
        if nominal is not None and family!='axel':raise ValueError('Axel nominal without Axel label')
        if scope in ['protocol_only','manual_contact','protocol_supported_contact_observation'] and (family is not None or nominal is not None):
            raise ValueError('Protocol/editor metadata is not visual expert truth')
        if event.get('modelTrainingEligible') and family is None:raise ValueError('Unknown labels are not training examples')
        last,first=event.get('lastContactFrame'),event.get('firstContactFrame')
        if (last is None)!=(first is None):raise ValueError('Half specified contact frames')
        if last is not None and (type(last) is not int or type(first) is not int or not 0<=last<first):
            raise ValueError('Invalid contact frames')
        a,b=event.get('startSeconds'),event.get('endSeconds')
        if (a is None)!=(b is None):raise ValueError('Half specified interval')
        if a is not None and (type(a) not in [int,float] or type(b) not in [int,float]
                              or not math.isfinite(a) or not math.isfinite(b) or not 0<=a<b):raise ValueError('Invalid event interval')
    return True


def validate_splits(sources,partitions,require_independence=False):
    by_hash={r['sourceSha256']:r for r in sources};seen=set();groups={}
    for name,hashes in partitions.items():
        if len(hashes)!=len(set(hashes)) or not set(hashes)<=set(by_hash):raise ValueError('Invalid partition sources')
        if seen&set(hashes):raise ValueError('Source overlap')
        seen.update(hashes);athletes=set();recordings=set()
        for h in hashes:
            source=by_hash[h];athletes.update(a for a in source.get('athleteIds',[source.get('athleteId')]) if a)
            if source.get('originalRecordingId'):recordings.add(source['originalRecordingId'])
            if require_independence and (not source.get('athleteIdentityVerified') or not source.get('recordingGroupVerified')):
                raise ValueError('Unverified athlete/original-recording identity')
        for previous,(pa,pr) in groups.items():
            if athletes&pa:raise ValueError('Athlete overlap: '+previous+'/'+name)
            if recordings&pr:raise ValueError('Original recording overlap: '+previous+'/'+name)
        groups[name]=(athletes,recordings)
    if require_independence and not partitions.get('confirmation'):raise ValueError('No frozen confirmation set')
    return True
