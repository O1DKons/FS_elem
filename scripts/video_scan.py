"""Fixed short-window candidate scan. Scores and intervals are not contacts or confidence."""
import math

def windows(duration,width=1.5,stride=.5):
 if not all(math.isfinite(v) and v>0 for v in (duration,width,stride)):raise ValueError('Positive finite duration/window/stride required')
 last=max(0.,duration-width)
 starts=[round(i*stride,6) for i in range(math.floor(last/stride)+1)]
 if last-starts[-1]>1e-6:starts.append(round(last,6))
 return [(s,min(duration,s+width)) for s in starts]

def select_candidates(rows):
 proposed=[]
 for row in rows:
  scores=row['prediction']['raw_scores'];axels={k:v for k,v in scores.items() if k in ('1A','2A','3A')}
  if not axels or 'other' not in scores:continue
  label=max(axels,key=axels.get);margin=axels[label]-scores['other']
  if margin<=0:continue
  proposed.append(dict(start=row['start'],end=row['end'],elementProposal=label,uncalibratedMargin=margin,rotationAssessment=None,measuredRevolutions=None))
 kept=[]
 for row in sorted(proposed,key=lambda r:-r['uncalibratedMargin']):
  if any(max(0,min(row['end'],k['end'])-max(row['start'],k['start']))/min(row['end']-row['start'],k['end']-k['start'])>.3 for k in kept):continue
  kept.append(row)
 return sorted(kept,key=lambda r:r['start'])
