import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateAnalysisResult} from '../contracts/analysis-result.mjs';
const result=()=>({schemaVersion:1,kind:'pose2d',status:'model_proposal',videoId:'v',sourceSha256:'a'.repeat(64),model:{name:'example',version:'1',weightsSha256:'b'.repeat(64)},coordinateSpace:{type:'image-normalized',width:1920,height:1080},frames:[{frameIndex:0,time:0,landmarks:[{name:'left_shoulder',x:.2,y:.4,confidence:.8}]},{frameIndex:2,time:.07,landmarks:[]}]});
test('model proposal has explicit provenance, coordinates and missing detections',()=>assert.equal(validateAnalysisResult(result()),true));
test('rejects ground truth claims, invalid coordinates, duplicate frames and landmarks',()=>{
 for(const change of [r=>r.status='confirmed',r=>r.frames[0].landmarks[0].x=NaN,r=>r.frames[0].landmarks[0].x=1.1,r=>r.frames[0].landmarks[0].confidence=-.1,r=>r.frames[1].frameIndex=0,r=>r.frames[1].time=0,r=>r.frames[0].landmarks.push({...r.frames[0].landmarks[0]}),r=>r.sourceSha256='bad',r=>r.coordinateSpace.type='meters',r=>r.groundTruth=true]){
  const r=result();change(r);assert.throws(()=>validateAnalysisResult(r));
 }
});
test('binding a proposal to a video checks its hash and exact frame timestamps',()=>{
 const context={videoId:'v',sourceSha256:'a'.repeat(64),times:[0,.03,.07]};
 assert.equal(validateAnalysisResult(result(),context),true);
 for(const patch of [{videoId:'other'},{sourceSha256:'f'.repeat(64)},{times:[0,.03,.09]}])assert.throws(()=>validateAnalysisResult(result(),{...context,...patch}));
});
