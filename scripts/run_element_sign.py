"""Reproducible sign experiment, grouped by athlete; never reads protocol codes."""
import json,hashlib,html
from pathlib import Path
import numpy as np
from element_sign import explicit_label,features,evaluate_signs
ROOT=Path(__file__).resolve().parents[1]
def main():
 paths=['data/rotation-expert-v1/resolved/revision-2/assessments.json','data/axel-demo-v1/boot-workbench-data.json']
 labels,manifest=[json.loads((ROOT/p).read_text()) for p in paths]
 byid={i['attemptId']:i for i in manifest['items']};records=[];excluded=[]
 for a in labels['assessments']:
  label=explicit_label(a);item=byid.get(a['attemptId'])
  if label is None or item is None:excluded.append(a['attemptId']);continue
  if item['sourceSha256']!=a['sourceSha256'] or item['firstContact']!=a['firstContact']:raise ValueError('Provenance mismatch')
  values=features(item)
  if values[0]<3/11:excluded.append(a['attemptId']);continue
  records.append(dict(attemptId=a['attemptId'],athlete=item['athlete'],truth=label,features=values,firstContact=item['firstContact']))
 result=evaluate_signs(np.array([r['features'] for r in records]),np.array([r['truth'] for r in records]),[r['athlete'] for r in records])
 result.update(records=records,excluded=excluded,inputSha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},scope='Development only; known Axel windows and manual contacts. 2A prefix from dataset, not recognition. Labels explicit in expert notes only. No protocol labels or identity features. Fixed nearest centroid, training-only scaling. No tuning. q unseen in its held-out fold. Previously inspected single-event data, not an independent benchmark.')
 # Serialize missing features as null.
 for r in records:r['features']=[float(x) if np.isfinite(x) else None for x in r['features']]
 out=ROOT/'work/step35-element-sign';out.mkdir(exist_ok=True,parents=True)
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 title='Experimental element sign / Предварительный знак элемента'
 rows=[]
 for r,p in zip(records,result['predictions']):
  url='boot-workbench.html?attempt='+r['attemptId']+'&frame='+str(r['firstContact'])+'&side=landing'
  rows.append('<tr><td><a href="'+url+'">'+html.escape(r['athlete']+' · '+r['attemptId'])+'</a></td><td>'+html.escape(p)+'</td><td>'+html.escape(r['truth'])+'</td><td>'+('OK' if p==r['truth'] else 'Mismatch')+'</td></tr>')
 page='<!doctype html><meta charset="utf-8"><title>'+title+'</title><style>body{background:#101923;color:#e5edf4;font:17px system-ui;max-width:1100px;margin:40px auto;padding:20px}a{color:#87d3ff}td,th{padding:12px;border-bottom:1px solid #425064;text-align:left}</style><a href="boot-workbench.html">← Boot workbench</a><h1>'+title+'</h1><p>Research experiment; requires review. Known double Axel clips, not automatic element recognition. Predicted signs below are held-out by athlete.</p><p>Correct: '+str(result['metrics']['correct'])+'/'+str(len(records))+'. Majority baseline: '+str(result['majorityMetrics']['correct'])+'/'+str(len(records))+'. Macro recall: '+str(round(result['metrics']['macroRecall']*100,1))+'%.</p><p>One q example: this class cannot be learned in its held-out fold. No reliable degree estimate. These development data were previously inspected; no independent accuracy claim.</p><table><tr><th>Attempt / кадр приземления</th><th>Model proposal</th><th>Expert label</th><th>Match</th></tr>'+''.join(rows)+'</table>'
 (ROOT/'data/axel-demo-v1/element-sign-results.html').write_text(page)
 print(json.dumps({k:result[k] for k in ['metrics','majorityMetrics','excluded']},indent=2))
if __name__=='__main__':main()
