"""Conservative offline short-side-swap hypotheses; not anatomical ground truth.
Only complete six-point chains with two-sided context are considered.
No coordinate smoothing, no image evidence, no use of manual annotations.
"""
import copy
import math

REGIONS={'arms':('shoulder','elbow','wrist'),'legs':('hip','knee','ankle')}
CONFIG=dict(maxFrames=3,minScore=.3,minGainDiagonal=.01,maxCostRatio=.6,minSeparationDiagonal=.005,contextRadius=2)

def opposite(name):
    return ('right_' if name.startswith('left_') else 'left_')+name.split('_',1)[1]


def ambiguous_joints(landmarks,region,width,height):
    """Coincident bilateral joints are ambiguous, not proven anatomically wrong."""
    points={p['name']:p for p in landmarks}
    threshold=math.hypot(width,height)*CONFIG['minSeparationDiagonal']
    result=[]
    for part in REGIONS[region]:
        a,b=points.get('left_'+part),points.get('right_'+part)
        if a and b and math.hypot((a['x']-b['x'])*width,(a['y']-b['y'])*height)<threshold:
            result.append(part)
    return result


def propose(frames,width,height):
    maps=[{p['name']:p for p in f['landmarks']} for f in frames]
    diag=math.hypot(width,height)
    dist=lambda a,b:math.hypot((a['x']-b['x'])*width,(a['y']-b['y'])*height)
    candidates=[]
    for region,parts in REGIONS.items():
        keys=[side+'_'+part for side in ('left','right') for part in parts]
        for start in range(2,len(frames)-2):
            for size in range(1,CONFIG['maxFrames']+1):
                end=start+size-1
                if end+2>=len(frames):break
                window=frames[start-2:end+3]
                if any(b['frameIndex']!=a['frameIndex']+1 or not 0<b['time']-a['time']<=.021 for a,b in zip(window,window[1:])):continue
                if any(k not in points or points[k]['confidence']<CONFIG['minScore'] for points in maps[start-2:end+3] for k in keys):continue
                if any(ambiguous_joints(f['landmarks'],region,width,height) for f in window):continue
                left,right=maps[start-1],maps[end+1]
                # Endpoints themselves must support the same identity convention.
                endpoint_direct=sum(dist(left[k],right[k]) for k in keys)
                endpoint_swapped=sum(dist(left[k],right[opposite(k)]) for k in keys)
                if endpoint_direct>=endpoint_swapped*.75:continue
                original,swapped=0,0
                for index in range(start,end+1):
                    t=(frames[index]['time']-frames[start-1]['time'])/(frames[end+1]['time']-frames[start-1]['time'])
                    for k in keys:
                        reference={axis:left[k][axis]*(1-t)+right[k][axis]*t for axis in ('x','y')}
                        original+=dist(maps[index][k],reference)
                        swapped+=dist(maps[index][opposite(k)],reference)
                count=size*len(keys);original/=count;swapped/=count
                if original-swapped<=diag*CONFIG['minGainDiagonal'] or swapped>=original*CONFIG['maxCostRatio']:continue
                # Both temporal edges must support swapping; a single weak edge is insufficient.
                if any(sum(dist(maps[idx][opposite(k)],anchor[k]) for k in keys)>=sum(dist(maps[idx][k],anchor[k]) for k in keys)*.8 for idx,anchor in ((start,left),(end,right))):continue
                candidates.append(dict(region=region,startFrame=frames[start]['frameIndex'],endFrame=frames[end]['frameIndex'],
                    contextFrames=[frames[i]['frameIndex'] for i in (start-2,start-1,end+1,end+2)],
                    originalResidualPx=original,swappedResidualPx=swapped,gainPx=original-swapped,
                    status='unverified_hypothesis',usesManualLabels=False))
    # Select disjoint windows per region from the unmodified input (no cascading edits).
    return select_nonconflicting(candidates)


def select_nonconflicting(candidates):
    result=[];occupied=set();protected=set()
    for candidate in sorted(candidates,key=lambda c:-c['gainPx']):
        touched={(candidate['region'],n) for n in range(candidate['startFrame'],candidate['endFrame']+1)}
        context={(candidate['region'],n) for n in candidate['contextFrames']}
        if (occupied|protected)&touched or occupied&context:continue
        result.append(candidate);occupied.update(touched);protected.update(context)
    return sorted(result,key=lambda c:(c['startFrame'],c['region']))


def apply(frames,proposals):
    result=copy.deepcopy(frames)
    for f in result:
        for proposal in proposals:
            if proposal['startFrame']<=f['frameIndex']<=proposal['endFrame']:
                parts=REGIONS[proposal['region']]
                for point in f['landmarks']:
                    if point['name'].split('_',1)[-1] in parts:
                        point['name']=opposite(point['name'])
    return result
