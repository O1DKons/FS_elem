"""Public API projection of actual inference observations. No fitted model or filling."""
import json
import math
from pathlib import Path

NAMES = ['nose','left_eye','right_eye','left_ear','right_ear','left_shoulder','right_shoulder',
         'left_elbow','right_elbow','left_wrist','right_wrist','left_hip','right_hip',
         'left_knee','right_knee','left_ankle','right_ankle','left_big_toe','left_small_toe',
         'left_heel','right_big_toe','right_small_toe','right_heel']
EDGES = [[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],
         [12,14],[14,16],[15,17],[15,19],[17,18],[16,20],[16,22],[20,21]]


def source_metadata(record):
    return {'sha256':record['sourceSha256'], 'width':record['width'], 'height':record['height'],
            'fps':record['fps'], 'frameCount':record['frameCount'],
            'durationSeconds':record.get('duration',record.get('durationSeconds')),
            'rotationDegrees':record.get('rotationDegrees',0)}


def export_pose(job_id, timeline, sparse, dense):
    source=source_metadata(timeline)
    frames={}
    def add(row,density,candidate=None):
        n=row['frameIndex'];t=row['time']
        if (type(n) is not int or not 0<=n<timeline['frameCount'] or not math.isfinite(t)
                or abs(t-timeline['timestampsSeconds'][n])>1e-6):
            raise ValueError('Pose observation does not match actual source frame/PTS')
        points=row.get('rawPoints',row.get('points',[]));scores=row.get('rawScores',row.get('scores',[]))
        if not points and not scores:converted=[None]*23
        else:
            if len(points)!=23 or len(scores)!=23:raise ValueError('Expected raw RTMW23 observation')
            converted=[]
            for point,score in zip(points,scores):
                if len(point)!=2:raise ValueError('Invalid point shape')
                x,y=map(float,point);score=float(score)
                valid=all(math.isfinite(v) for v in [x,y,score]) and 0<=x<source['width'] and 0<=y<source['height']
                converted.append({'x':x,'y':y,'confidence':score} if valid else None)
        previous=frames.get(n)
        if previous and density=='sparse':return
        # Overlapping dense windows may disagree; keep the first actual observation.
        if previous and previous['density']=='dense' and density=='dense':return
        frames[n]={'frameIndex':n,'timeSeconds':t,'density':density,'candidateId':candidate,'points':converted}
    for row in sparse['frames']:add(row,'sparse')
    for item in dense.get('items',[]):
        for row in item['frames'].values():add(row,'dense',item['window']['candidateId'])
    return {'schemaVersion':1,'jobId':job_id,'source':source,'layout':'coco-wholebody-first23',
            'coordinateSpace':'displayed-source-pixels','scoreKind':'raw-heatmap-peak',
            'maxNearestSeconds':{'sparse':.065,'dense':.025},'keypointNames':NAMES,'edges':EDGES,
            'frames':[frames[n] for n in sorted(frames)]}


def export_result(job_id, raw):
    source=source_metadata(dict(raw['sourceMetadata'],sourceSha256=raw['sourceSha256']))
    events=[]
    for row in raw['events']:
        if row['family']!='axel':continue
        nominal=row.get('nominal')
        if nominal not in (None,'1A','2A'):raise ValueError('Unsupported nominal class')
        events.append({'id':row['id'],'startSeconds':row['start'],'endSeconds':row['end'],'family':'axel',
            'nominal':nominal,'nominalRevolutions':{'1A':1.5,'2A':2.5}.get(nominal),
            'nominalReason':row.get('nominalReason'),'scoresUncalibrated':row.get('nominalScoresUncalibrated'),
            'physicalAirborneTurns':None,'underrotation':None})
    models={role:{k:v for k,v in model.items() if k in ['sha256','originalSha256','protocolSha256','groupId']}
            for role,model in raw.get('models',{}).items()}
    return {'schemaVersion':1,'jobId':job_id,'status':'completed','source':source,'events':events,
            'candidateCount':len(raw['events']),'noEvents':not events,
            'provenance':{'recipeSha256':raw['recipeSha256'],'models':models,
                'poseSha256':raw.get('poseSha256'),'detectorSha256':raw.get('detectorSha256'),
                'exactSourceTrainingOverlap':raw.get('exactSourceTrainingOverlap',{}),
                'globalAthleteIndependenceVerified':False,'goal70Verified':False},
            'timings':raw.get('timings',{}),'limitations':raw.get('limitations',[])}


def publish(job_id, raw, output):
    cache=Path(raw['cacheDirectory'])
    read=lambda name:json.loads((cache/name).read_text())
    result=export_result(job_id,raw)
    pose=export_pose(job_id,read('timeline.json'),read('sparse.json'),read('dense.json'))
    if result['source']!=pose['source']:raise ValueError('Result/pose source geometry differs')
    for name,value in [('result.json',result),('pose.json',pose)]:
        with (Path(output)/name).open('x') as stream:json.dump(value,stream,ensure_ascii=False,allow_nan=False)
