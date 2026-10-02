"""Fixed flight ablation on the same 19 reviewed attempts; no parameter search."""
import hashlib,json,html
from pathlib import Path
import numpy as np
from element_sign import features,flight_features,evaluate_signs
ROOT=Path(__file__).resolve().parents[1]
def main():
 paths=['work/step35-element-sign/results.json','work/step30-image-motion/results.json','data/axel-demo-v1/boot-workbench-data.json']
 base,motion,manifest=[json.loads((ROOT/p).read_text()) for p in paths]
 hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
 # Refuse stale image-motion cache instead of silently comparing incompatible sources.
 for p,digest in motion['inputSha256'].items():
  if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest:raise ValueError('Stale motion input: '+p)
 for p,digest in base['inputSha256'].items():
  if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest:raise ValueError('Stale sign input: '+p)
 items={i['attemptId']:i for i in manifest['items']};boots=[];flights=[]
 for record in base['records']:
  item=items[record['attemptId']]
  if item['athlete']!=record['athlete']:raise ValueError('Group mismatch')
  path='work/step30-image-motion/'+record['attemptId']+'.flow.json'
  hashes[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
  boots.append(features(item));flights.append(flight_features(json.loads((ROOT/path).read_text()),item['lastContact'],item['firstContact']))
 y=np.array([r['truth'] for r in base['records']]);groups=[r['athlete'] for r in base['records']]
 variants={name:evaluate_signs(x,y,groups) for name,x in [('boot',np.array(boots)),('flight',np.array(flights)),('combined',np.column_stack([boots,flights]))]}
 assert variants['boot']['predictions']==base['predictions']
 result=dict(inputSha256=hashes,records=base['records'],flightFeatures=flights,variants=variants,method='Fixed nearest centroid, training-only scaling/imputation, leave athlete out; six flow mean/std features from strictly airborne pairs. Same 19 attempts. No tuning. Development only, not independent evaluation.')
 out=ROOT/'work/step36-element-sign-flight';out.mkdir(parents=True,exist_ok=True)
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 rows=[]
 for i,r in enumerate(base['records']):
  cells=[html.escape(r['athlete']+' '+r['attemptId']),html.escape(r['truth'])]+[html.escape(variants[v]['predictions'][i]) for v in ['boot','flight','combined']]
  rows.append('<tr>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>')
 summaries=''.join('<p>'+name+': '+str(v['metrics']['correct'])+'/19; macro recall '+str(round(v['metrics']['macroRecall']*100,1))+'%</p>' for name,v in variants.items())
 page='<meta charset="utf-8"><title>Flight feature comparison</title><style>body{font:17px system-ui;background:#101923;color:#eef;margin:40px}td,th{padding:12px;border-bottom:1px solid #456}a{color:#8df}</style><h1>Flight feature comparison</h1><p>Development experiment. Known 2A windows and manual contacts; not automatic jump recognition. All attempts of each tested athlete excluded from training. Same 19 attempts, no tuning.</p>'+summaries+'<p>Boot / flight / combined. No independent accuracy claim. Single q example cannot be learned in its held-out fold.</p><table><tr><th>Attempt</th><th>Expert</th><th>Boot</th><th>Flight</th><th>Combined</th></tr>'+''.join(rows)+'</table><p><a href="element-sign-results.html">Previous experiment</a></p>'
 (ROOT/'data/axel-demo-v1/element-sign-flight.html').write_text(page)
 print(json.dumps({k:v['metrics'] for k,v in variants.items()},indent=2))
if __name__=='__main__':main()
