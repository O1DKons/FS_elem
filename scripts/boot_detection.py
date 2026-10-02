"""Conservative frame-local foot proposals from RTMW COCO-WholeBody.
Score is a model response, not calibrated probability. No ice-plane angles.
"""
import math


def candidates(points, scores, mirrored, mirror_scores, width, height, body_height):
    if any(len(v) < 23 for v in (points, scores, mirrored, mirror_scores)):
        raise ValueError('Expected COCO-WholeBody (at least 23 points)')
    if min(width, height, body_height) <= 0:
        raise ValueError('Positive image and body dimensions required')
    result = []
    for side, idx, other in [('left',17,20), ('right',20,17)]:
        raw = [list(map(float,points[j])) for j in range(idx,idx+3)]
        flip = [[width-1-float(mirrored[j][0]),float(mirrored[j][1])] for j in range(other,other+3)]
        confidence = [float(scores[j]) for j in range(idx,idx+3)] + [float(mirror_scores[j]) for j in range(other,other+3)]
        row = dict(side=side,heel=None,toe=None,score=0.,status='uncertain',reasons=[],imageHeadingDegrees=None)
        finite = all(math.isfinite(v) for p in raw+flip for v in p) and all(math.isfinite(v) for v in confidence)
        if not finite or any(not (0<=p[0]<width and 0<=p[1]<height) for p in raw+flip):
            row['reasons']=['invalid_or_outside'];result.append(row);continue
        score=min(confidence);row['score']=max(0.,min(1.,score))
        toe=[(raw[0][k]+raw[1][k])/2 for k in range(2)];heel=raw[2]
        ft=[(flip[0][k]+flip[1][k])/2 for k in range(2)];fh=flip[2]
        length=math.dist(toe,heel);disagreement=max(math.dist(toe,ft),math.dist(heel,fh))
        row.update(toe=toe,heel=heel,projectedLength=length,mirrorDisagreementPixels=disagreement)
        if score<.5:row['reasons'].append('low_model_response')
        if length<max(10.,.02*body_height):row['reasons'].append('foreshortened')
        if length>.3*body_height:row['reasons'].append('implausible_span')
        if disagreement>max(6.,.2*length):row['reasons'].append('mirror_disagreement')
        if not row['reasons']:
            row['status']='visible';row['imageHeadingDegrees']=math.degrees(math.atan2(toe[1]-heel[1],toe[0]-heel[0]))
        result.append(row)
    if all(r['toe'] is not None for r in result):
        centers=[[(r['toe'][k]+r['heel'][k])/2 for k in range(2)] for r in result]
        if math.dist(*centers)<.4*max(r['projectedLength'] for r in result):
            for row in result:
                row['reasons'].append('feet_overlap');row['status']='uncertain';row['imageHeadingDegrees']=None
    return result


def temporal_checks(frames):
    """Flag ambiguous transitions; never swap sides or carry predictions over gaps.

    Compare original adjacent detections, not the filtered output. A rejected
    transition therefore does not prevent independent recovery next frame.
    """
    import copy
    result=copy.deepcopy(frames)
    def center(c):return [(c['heel'][k]+c['toe'][k])/2 for k in range(2)]
    def flag(c,reason):
        if reason not in c['reasons']:c['reasons'].append(reason)
        c['status']='uncertain';c['imageHeadingDegrees']=None
    for i in range(1,len(frames)):
        if frames[i]['frameIndex']!=frames[i-1]['frameIndex']+1:continue
        before={c['side']:c for c in frames[i-1]['candidates'] if c['status']=='visible'}
        current={c['side']:c for c in frames[i]['candidates'] if c['status']=='visible'}
        output={c['side']:c for c in result[i]['candidates']}
        for side in before.keys()&current.keys():
            a,b=before[side],current[side]
            difference=abs((b['imageHeadingDegrees']-a['imageHeadingDegrees']+180)%360-180)
            if difference>100:flag(output[side],'orientation_jump')
        if len(before)==len(current)==2:
            direct=sum(math.dist(center(before[s]),center(current[s])) for s in ('left','right'))
            swapped=math.dist(center(before['left']),center(current['right']))+math.dist(center(before['right']),center(current['left']))
            margin=.2*max(c['projectedLength'] for c in current.values())
            if swapped+margin<direct and swapped<.7*direct:
                for c in output.values():flag(c,'side_identity_change')
    return result


def landing_candidates(frames, first_contact):
    """Proposal for the lower skate near landing, never a contact classifier.

    Uses image y, not world height. Perspective/falls can defeat this heuristic.
    Does not fall back to the clear free foot if the lower foot is uncertain.
    Anatomical side proposals remain untouched and available for review.
    """
    import copy
    result=copy.deepcopy(frames);previous=None;previous_index=None
    for frame in result:
        selected=dict(side='landing',toe=None,heel=None,score=0.,status='uncertain',reasons=[],imageHeadingDegrees=None)
        valid=[c for c in frame['candidates'] if c['side'] in ('left','right') and c['toe'] is not None and c['heel'] is not None]
        if frame['frameIndex']<first_contact-2:selected['reasons']=['outside_landing_window']
        elif len(valid)!=2:selected['reasons']=['landing_candidates_missing']
        else:
            valid.sort(key=lambda c:max(c['toe'][1],c['heel'][1]),reverse=True)
            lower,other=valid;selected=copy.deepcopy(lower);selected.update(side='landing',sourceSide=lower['side'])
            gap=max(lower['toe'][1],lower['heel'][1])-max(other['toe'][1],other['heel'][1])
            if gap<max(5.,.15*max(c['projectedLength'] for c in valid)):
                selected['reasons'].append('landing_choice_ambiguous')
            if previous is not None and previous_index==frame['frameIndex']-1:
                center=lambda c:[(c['toe'][k]+c['heel'][k])/2 for k in range(2)]
                if math.dist(center(previous),center(selected))>max(40.,1.5*previous['projectedLength']):selected['reasons'].append('landing_motion_jump')
            if selected['reasons'] or lower['status']!='visible':selected['status']='uncertain';selected['imageHeadingDegrees']=None
        frame['candidates'].append(selected)
        previous=selected if selected['status']=='visible' else None;previous_index=frame['frameIndex']
    return result
