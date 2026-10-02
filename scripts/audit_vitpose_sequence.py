"""Read-only sequence audit: rank candidates, export every source frame with overlays.
Metrics nominate review candidates; they do not establish anatomical side correctness.
"""
import json, math, hashlib
from pathlib import Path
from PIL import Image, ImageDraw
from rtmpose_adapter import COCO_NAMES
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/step27-audit'
EDGES=[(5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,13),(13,15),(12,14),(14,16),(5,6),(11,12)]
def main():
 OUT.mkdir(parents=True,exist_ok=True); result={}; total=0
 for path in sorted((ROOT/'data/pose-vitpose-pilot-v1').glob('competition-*.json')):
  if '.raw.' in path.name or '.anchors.' in path.name:continue
  seq=json.loads(path.read_text()); raw=json.loads(path.with_suffix('.raw.json').read_text()); frames=seq['frames']; rows=[]; cells=[]
  for n,(f,r) in enumerate(zip(frames,raw)):
   idx=f['frameIndex']; pts=r['keypointsPixels']; src=ROOT/f'work/step6-pose/{path.stem}/{idx:06d}.png'; im=Image.open(src).convert('RGB'); w,h=im.size
   err=max(math.dist((p['x']*w,p['y']*h),q) for p in f['landmarks'] for q in [pts[COCO_NAMES.index(p['name'])]])
   lengths=[math.dist(pts[a],pts[b]) for a,b in EDGES]; torso=(lengths[4]+lengths[5])/2
   jump=max((math.dist(pts[j],raw[n-1]['keypointsPixels'][j]) for j in range(5,17)),default=0)/max(torso,1) if n else 0
   row={'frame':idx,'time':f['time'],'minBodyScore':min(r['scores'][5:]),'maxJointStepTorso':jump,'maxNormalizationErrorPx':err,'sourceHashMatches':hashlib.sha256(src.read_bytes()).hexdigest()==r['sourceFrameSha256']}; rows.append(row)
   x0,y0,x1,y1=r['selectedBox']; pad=35; box=(max(0,int(x0-pad)),max(0,int(y0-pad)),min(w,int(x1+pad)),min(h,int(y1+pad))); crop=im.crop(box); scale=min(242/crop.width,265/crop.height); crop=crop.resize((round(crop.width*scale),round(crop.height*scale))); cell=Image.new('RGB',(250,300),'#18232c'); ox=(250-crop.width)//2; oy=27; cell.paste(crop,(ox,oy)); d=ImageDraw.Draw(cell); d.text((5,5),f'{idx}  {f["time"]:.2f}s',fill='white'); coords=[((x-box[0])*scale+ox,(y-box[1])*scale+oy) for x,y in pts]
   for a,b in EDGES:d.line([coords[a],coords[b]],fill=('#ff55aa' if a%2 else '#39dcff'),width=2)
   for j in range(5,17):
    x,y=coords[j]; d.ellipse((x-2,y-2,x+2,y+2),fill=('#ff55aa' if j%2 else '#39dcff'))
   cells.append(cell)
  for start in range(0,len(cells),25):
   page=Image.new('RGB',(1250,1500),'#101820')
   for k,cell in enumerate(cells[start:start+25]):page.paste(cell,((k%5)*250,(k//5)*300))
   page.save(OUT/f'{path.stem}-{start//25+1}.jpg',quality=92)
  result[path.stem]={'count':len(rows),'rows':rows,'topStepCandidates':sorted(rows,key=lambda x:x['maxJointStepTorso'],reverse=True)[:12],'lowConfidenceCandidates':sorted(rows,key=lambda x:x['minBodyScore'])[:12]}; total+=len(rows)
 (OUT/'metrics.json').write_text(json.dumps({'total':total,'clips':result},indent=2)); print('Audited',total,'frames; artifacts',OUT)
 for name,v in result.items():print(name,'jumps',[(x['frame'],round(x['maxJointStepTorso'],2)) for x in v['topStepCandidates'][:8]],'low',[(x['frame'],round(x['minBodyScore'],2)) for x in v['lowConfidenceCandidates'][:8]])
if __name__=='__main__':main()
