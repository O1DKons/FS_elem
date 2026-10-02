import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
export function fixture(t) {
 const root=mkdtempSync(join(tmpdir(),'fs-elem-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
 const source=join(root,'old');const dest=join(root,'new');
 for(const name of ['jump-marker/data','jump-marker/frames','axel-15','ssd-personal-videos']) mkdirSync(join(source,name),{recursive:true});
 const media=Buffer.from('a-small-video-fixture');
 const catalog=[{id:'01',filename:'sample.mp4',duration:.2,frameCount:4,sha256:createHash('sha256').update(media).digest('hex'),title:'Original name',custom:{retained:true}}];
 const episodes=[{id:'attempt-1',videoId:'01',start:0,end:.1,startFrame:0,endFrame:2,note:'original',attemptGroup:'replay-a',custom:'keep'}];
 const annotations={schemaVersion:1,revision:12,boundaryDefinition:'source seconds',episodes};
 const expert={schemaVersion:1,source:'trainer',scope:'type only; boundaries unconfirmed',labels:[{videoId:'01',element:'1A',underrotation:'none_stated',verbatim:'1А'}]};
 const json=(name,value)=>writeFileSync(join(source,name),JSON.stringify(value));
 json('jump-marker/catalog.json',catalog);json('jump-marker/data/annotations.json',annotations);json('jump-marker/frames/01.json',[0,.05,.1,.15]);json('ssd-personal-videos/expert-element-labels.json',expert);
 writeFileSync(join(source,'axel-15/sample.mp4'),media);
 return {root,source,dest,catalog,annotations,expert,media,json};
}
