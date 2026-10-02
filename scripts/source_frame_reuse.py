"""Reuse identical source observations, never standardized time slots as evidence."""
import copy,math,re

def source_key(frame):
 index=frame.get('sourceFrameIndex');digest=frame.get('sourceFrameSha256')
 if not isinstance(index,int) or isinstance(index,bool) or index<0 or not isinstance(digest,str) or re.fullmatch('[0-9a-fA-F]{64}',digest) is None:return None
 return index,digest.lower()

class SourceFrameCache:
 def __init__(self):self.values={}
 def compute(self,frame,infer):
  key=source_key(frame)
  if key is not None and key in self.values:return copy.deepcopy(self.values[key]),True
  value=infer()
  if key is not None:self.values[key]=copy.deepcopy(value)
  return copy.deepcopy(value),False

def independent_intervals(item):
 visible={}
 for frame in item['frames']:
  offset=frame['frameIndex']-item['firstContact']
  if not 0<=offset<=10:continue
  c=next((x for x in frame['candidates'] if x['side']=='landing' and x['status']=='visible'),None)
  if c is None:continue
  heel,toe=c.get('heel'),c.get('toe')
  if heel is None or toe is None or len(heel)!=2 or len(toe)!=2 or not all(math.isfinite(v) for v in heel+toe) or math.dist(heel,toe)<=0:continue
  visible[offset]=frame
 count=0;standardized=0
 for index in range(1,11):
  if index not in visible or index-1 not in visible:continue
  standardized+=1;a,b=source_key(visible[index-1]),source_key(visible[index])
  # Both a new original frame and changed decoded pixels are necessary.
  if a is not None and b is not None and a[0]!=b[0] and a[1]!=b[1]:count+=1
 keys=[source_key(f) for f in visible.values()]
 return dict(independentSourceIntervals=count,standardizedIntervals=standardized,sourceProvenanceComplete=bool(keys) and all(k is not None for k in keys),distinctSourceFrames=len({k[0] for k in keys if k is not None}),distinctImageFrames=len({k[1] for k in keys if k is not None}))
