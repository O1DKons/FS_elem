import {readFileSync,existsSync,mkdirSync,mkdtempSync,copyFileSync,writeFileSync,renameSync,rmSync,createReadStream,realpathSync} from 'node:fs';
import {resolve,join,basename,dirname,relative,sep} from 'node:path';
import {createHash} from 'node:crypto';
import {validateCatalog,validateDocument} from './validation.mjs';
import {initializeDatabase,openStore} from './store.mjs';
const digest=buffer=>createHash('sha256').update(buffer).digest('hex');
async function fileHash(path) {const h=createHash('sha256');for await(const chunk of createReadStream(path)) h.update(chunk);return h.digest('hex');}

export async function importLegacy(source, destination, {dryRun=false}={}) {
  source=realpathSync(resolve(source));
  let ancestor=resolve(destination);const tail=[];
  while(!existsSync(ancestor)) {tail.unshift(basename(ancestor));ancestor=dirname(ancestor);}
  destination=join(realpathSync(ancestor),...tail);
  if(destination===source || destination.startsWith(source+sep) || source.startsWith(destination+sep)) throw Error('Source and destination must be separate');
  const snapshots=[];
  function read(name) {
    const bytes=readFileSync(join(source,name));
    snapshots.push({name,bytes,sha256:digest(bytes)});
    return JSON.parse(bytes.toString('utf8'));
  }
  const catalog=read('jump-marker/catalog.json');
  const annotations=read('jump-marker/data/annotations.json');
  const frames=Object.fromEntries(catalog.map(v=>{
    if(typeof v.id!=='string' || !/^[a-zA-Z0-9_-]+$/.test(v.id)) throw Error('Invalid video id');
    return [v.id,read(`jump-marker/frames/${v.id}.json`)];
  }));
  const expert=read('ssd-personal-videos/expert-element-labels.json');
  validateCatalog(catalog,frames);validateDocument(annotations,catalog,frames);
  if(annotations.schemaVersion!==1) throw Error('Expected legacy schemaVersion 1');
  if(!Array.isArray(expert.labels)) throw Error('Invalid expert labels');
  for(const label of expert.labels) {
    if(!catalog.some(v=>v.id===label.videoId) || typeof label.element!=='string' || typeof label.underrotation!=='string') throw Error('Invalid expert label');
  }
  const media=[];
  for(const v of catalog) {
    if(typeof v.filename!=='string' || basename(v.filename)!==v.filename) throw Error('Invalid media filename');
    const collection=v.collection??'playlist';
    const directory={playlist:'axel-15',personal:'personal-videos/media','ssd-personal':'ssd-personal-videos/media'}[collection];
    if(!directory) throw Error(`Unknown collection ${collection}`);
    const path=join(source,directory,v.filename);const hash=await fileHash(path);
    if(hash!==v.sha256) throw Error(`Media checksum mismatch: ${v.id}`);
    media.push({id:v.id,path,sha256:hash});
  }
  const inputs=[...snapshots.map(({name,sha256})=>({name,sha256})),...media.map(m=>({name:relative(source,m.path),sha256:m.sha256}))];
  const fingerprint=digest(JSON.stringify(inputs));
  const report={schemaVersion:2,status:dryRun?'dry_run':'imported',fingerprint,source,videos:catalog.length,episodes:annotations.episodes.length,labels:expert.labels.length,revision:annotations.revision,sourceFiles:inputs};
  if(existsSync(destination)) {
    const store=openStore(destination);
    try {if(store.importReport().fingerprint===fingerprint) return {...report,status:'already_imported'};}
    finally {store.close();}
    throw Error('Destination already contains a different import; no files changed');
  }
  if(dryRun) return report;
  mkdirSync(dirname(destination),{recursive:true});
  const lock=destination+'.import-lock';
  mkdirSync(lock); // Exclusive lock: never steal or remove another importer’s lock.
  let staging;
  try {
    if(existsSync(destination)) throw Error('Destination already exists');
    staging=mkdtempSync(join(dirname(destination),'.import-stage-'));
    mkdirSync(join(staging,'media'));mkdirSync(join(staging,'originals'));
    for(const m of media) {
      const target=join(staging,'media',m.id+'.mp4');copyFileSync(m.path,target);
      if(await fileHash(target)!==m.sha256) throw Error(`Copied media checksum mismatch: ${m.id}`);
    }
    for(const s of snapshots) {
      const target=join(staging,'originals',s.name);mkdirSync(dirname(target),{recursive:true});writeFileSync(target,s.bytes);
    }
    // Catch changes made by an open legacy editor during the import.
    for(const input of inputs) if(await fileHash(join(source,input.name))!==input.sha256) throw Error('Source changed during import; retry from a stable snapshot');
    initializeDatabase(join(staging,'fs-elem.sqlite'),{catalog,frames,annotations,expert,report});
    writeFileSync(join(staging,'import-report.json'),JSON.stringify(report,null,2)+'\n');
    renameSync(staging,destination);staging=undefined;
    return report;
  } finally {
    if(staging) rmSync(staging,{recursive:true,force:true});
    rmSync(lock,{recursive:true});
  }
}
