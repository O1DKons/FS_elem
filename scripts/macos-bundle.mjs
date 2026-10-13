// Import-safe Mac phase supervisor. No build, download or startup at module import.
import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import http from 'node:http';
import {fileURLToPath} from 'node:url';

const VERSION='0.2.6', META='macOS-bundle.json', STREAM_CAP=262144;
const PYTHON_VERSIONS={science:'3.12.15',pose:'3.9.20'};
const NATIVE={
  "status": "ready",
  "platform": {
    "system": "macOS",
    "architecture": "arm64",
    "minVersion": "13"
  },
  "environments": {
    "science": {
      "pythonMinor": "3.12",
      "lock": "services/analysis/requirements-science-macos-arm64.lock",
      "lockSha256": "1e40e7635b80402059c3be3b5e514fcd7812001640b5e426ee2e5c703f98a821",
      "packages": {
        "cloudpickle": "3.1.2",
        "imageio-ffmpeg": "0.6.0",
        "joblib": "1.6.0",
        "narwhals": "2.26.0",
        "numpy": "2.5.3",
        "scikit-learn": "1.9.0",
        "scipy": "1.18.1",
        "threadpoolctl": "3.6.0"
      }
    },
    "pose": {
      "pythonMinor": "3.9",
      "lock": "services/analysis/requirements-pose-macos-arm64.lock",
      "lockSha256": "4be74d2d4efcd57c700f3e81a4f96e1848338959c1f7f4ada9e33d6a8c7a17dd",
      "packages": {
        "coloredlogs": "15.0.1",
        "flatbuffers": "25.12.19",
        "humanfriendly": "10.0",
        "mpmath": "1.3.0",
        "numpy": "2.0.2",
        "onnxruntime": "1.19.2",
        "opencv-contrib-python": "5.0.0.93",
        "opencv-python": "5.0.0.93",
        "packaging": "26.3",
        "protobuf": "6.33.6",
        "rtmlib": "0.0.15",
        "sympy": "1.14.0",
        "tqdm": "4.70.1"
      }
    }
  },
  "ffmpeg": {
    "id": "ffmpeg",
    "path": ".runtime/bin/ffmpeg",
    "sizeBytes": 49368728,
    "sha256": "6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617",
    "distribution": "imageio-ffmpeg==0.6.0 macOS arm64 wheel; local installation only",
    "version": "7.1",
    "binaryLicense": "GPL-2.0-or-later (verified local executable -L)",
    "wrapperLicense": "BSD-2-Clause"
  }
};
const MODELS=[
  {
    "id": "flight",
    "path": "assets/models/flight.joblib",
    "sizeBytes": 1916697,
    "sha256": "9d6ca74b3de38dab1366c55f55b8de0bca6052ce1aa0c7dedd45ae17cf0140e7",
    "url": null,
    "format": "raw",
    "downloadSizeBytes": null,
    "downloadSha256": null,
    "origin": "app",
    "cacheDestination": null
  },
  {
    "id": "family",
    "path": "assets/models/family.joblib",
    "sizeBytes": 18228,
    "sha256": "1f696a6ab8a300320b7cdff5875ec22a6206ff32bd731c81db00f905529d5f72",
    "url": null,
    "format": "raw",
    "downloadSizeBytes": null,
    "downloadSha256": null,
    "origin": "app",
    "cacheDestination": null
  },
  {
    "id": "nominal",
    "path": "assets/models/nominal.joblib",
    "sizeBytes": 3097,
    "sha256": "f4c2e2b70400bd161a3c9bed62e5e892d6712134719a647a0dd53877bce792f1",
    "url": null,
    "format": "raw",
    "downloadSizeBytes": null,
    "downloadSha256": null,
    "origin": "app",
    "cacheDestination": null
  },
  {
    "id": "yolox",
    "path": "assets/models/yolox.onnx",
    "sizeBytes": 101400344,
    "sha256": "3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23",
    "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip",
    "format": "zip",
    "downloadSizeBytes": 94223081,
    "downloadSha256": null,
    "origin": "app",
    "cacheDestination": null
  },
  {
    "id": "rtmw",
    "path": "assets/models/rtmw.onnx",
    "sizeBytes": 229320930,
    "sha256": "bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054",
    "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip",
    "format": "zip",
    "downloadSizeBytes": 213433855,
    "downloadSha256": null,
    "origin": "app",
    "cacheDestination": null
  }
];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const sha=b=>createHash('sha256').update(b).digest('hex');
function ordered(x){if(Array.isArray(x))return x.map(ordered);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])]));return x;}
function canonical(x){return JSON.stringify(ordered(x)).replace(/[^\x00-\x7f]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));}
function equal(a,b){return canonical(a)===canonical(b);}
function hashValue(x){return typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);}
export function relativeName(x){
  if(typeof x!=='string'||!x||x.includes('\\')||x.includes(':')||x.startsWith('/')||x.split('/').some(p=>!p||p==='.'||p==='..'))throw Error('Invalid relative bundle name');
  return x;
}
function physical(root,name,canonicalRoot=fs.realpathSync(root)){
  relativeName(name);let p=root;
  for(const part of name.split('/')){p=path.join(p,part);if(fs.lstatSync(p).isSymbolicLink())throw Error('Linked bundle/cache path');}
  const real=fs.realpathSync(p),rel=path.relative(canonicalRoot,real);
  if(rel==='..'||rel.startsWith('../')||path.isAbsolute(rel)||!fs.lstatSync(p).isFile())throw Error('File escapes original admitted origin');
  return p;
}
function fingerprint(p){
  const s=fs.lstatSync(p,{bigint:true});if(!s.isFile())throw Error('Current file is not regular');
  const size=Number(s.size);if(!Number.isSafeInteger(size))throw Error('Unsafe file size');
  return {dev:String(s.dev),ino:String(s.ino),bytes:size,mtimeNs:String(s.mtimeNs),ctimeNs:String(s.ctimeNs)};
}
function shaFile(p){const fd=fs.openSync(p,'r'),buffer=Buffer.alloc(1024*1024),h=createHash('sha256');try{let n;while((n=fs.readSync(fd,buffer,0,buffer.length,null))>0)h.update(buffer.subarray(0,n));return h.digest('hex');}finally{fs.closeSync(fd);}}
function jsonFile(p){const s=fs.statSync(p);if(s.size>32*1024*1024)throw Error('Metadata cap exceeded');const b=fs.readFileSync(p);return {value:JSON.parse(b.toString('utf8')),sha256:sha(b)};}
export function validateRecipeBinding(rule,expected){
  if(!rule||rule.status!=='source-accepted')throw Error('Root recipe binding unresolved');
  for(const [role,name] of Object.entries({parent:'configs/axel-release-offline-macos-arm64-parent-v026.json',derived:'configs/axel-release-ort4-macos-app.json',modelManifest:'assets/models/manifest-offline-macos-v026.json'})){
    const row=rule[role];
    if(!row||row.path!==name||!Number.isSafeInteger(row.bytes)||row.bytes<=0||!hashValue(row.sha256)||expected.get(name)?.sha256!==row.sha256||expected.get(name)?.bytes!==row.bytes)throw Error('Root recipe/manifest inventory binding differs: '+role);
  }
  if(!Array.isArray(rule.sourceUpdates)||rule.sourceUpdates.length>128||!rule.packagingProvenance||Array.isArray(rule.packagingProvenance)||typeof rule.packagingProvenance!=='object')throw Error('Root Source update/provenance binding unresolved');
  const seen=new Set();
  for(const row of rule.sourceUpdates){
    const name=relativeName(row.path),key='../'+name;
    if(!/^(runtime|services|scripts)\//.test(name)||row.key!==key||seen.has(key)||!Number.isSafeInteger(row.bytes)||row.bytes<=0||!hashValue(row.sha256)||expected.get(name)?.sha256!==row.sha256||expected.get(name)?.bytes!==row.bytes)throw Error('Invalid/unbound Root Source update');
    seen.add(key);
  }
  return rule;
}
export function expectedMacRecipe(original,rule){
  const want=structuredClone(original);
  for(const row of rule.sourceUpdates){
    const key=row.key;
    const present=[want.inputSha256,want.backendSourceProvenance.runtimeHashes,want.backendSourceProvenance.runtimeBytes].map(table=>Object.hasOwn(table,key));
    const ownerAdditions=['scripts/macos-first-run.py','scripts/macos-bundle.mjs','scripts/start-macos-desktop.mjs'];
    if(!present.every(Boolean)&&!(present.every(x=>!x)&&ownerAdditions.includes(row.path)))throw Error('Root Source update outside original source maps or exact Main additions');
    want.inputSha256[key]=row.sha256;
    want.backendSourceProvenance.runtimeHashes[key]=row.sha256;
    want.backendSourceProvenance.runtimeBytes[key]=row.bytes;
  }
  want.packagingProvenance=rule.packagingProvenance;
  return want;
}
function staticBinding(appRoot,userRoot){
  if(!path.isAbsolute(appRoot)||!path.isAbsolute(userRoot))throw Error('Absolute app/user roots required');
  const canonicalApp=fs.realpathSync(appRoot),canonicalUser=fs.realpathSync(userRoot);
  const a=path.relative(canonicalApp,canonicalUser),b=path.relative(canonicalUser,canonicalApp);
  if(!a||(!a.startsWith('../')&&!path.isAbsolute(a))||!b||(!b.startsWith('../')&&!path.isAbsolute(b)))throw Error('App and user roots must be separate origins');
  const bundleDocument=jsonFile(physical(appRoot,META,canonicalApp)),m=bundleDocument.value;
  if(m.schemaVersion!==1||m.packageVersion!==VERSION||m.platformId!=='macos-arm64'||m.offline!==true||!equal(m.pythonVersions,PYTHON_VERSIONS))throw Error('Unsupported Mac package');
  if(m.nativeProfileSha256!==sha(Buffer.from(canonical(NATIVE))))throw Error('Native profile binding differs');
  if(!equal(m.interpreters,{science:'.runtime/venv-science/bin/python',pose:'.runtime/venv-pose/bin/python'}))throw Error('Interpreter map differs');
  if(m.node?.path!=='.runtime/bin/node'||m.node.major!==22||m.node.version!=='22.23.3')throw Error('Exact Node22 binding unresolved');
  if(m.recipePath!=='configs/axel-release-ort4-macos-app.json'||m.originalRecipePath!=='configs/axel-release-offline-macos-arm64-parent-v026.json'||m.modelManifestPath!=='assets/models/manifest-offline-macos-v026.json')throw Error('Root original/model paths differ');
  if(!Array.isArray(m.files)||m.files.length===0)throw Error('Missing authoritative inventory');
  const expected=new Map(),folded=new Set();
  for(const row of m.files){
    const name=relativeName(row.path),fold=name.toLowerCase();
    if(name===META||folded.has(fold)||!Number.isSafeInteger(row.bytes)||row.bytes<0||!hashValue(row.sha256))throw Error('Invalid authoritative inventory');
    expected.set(name,row);folded.add(fold);
  }
  for(const name of [m.recipePath,m.originalRecipePath,m.modelManifestPath,'services/analysis/process_owner.py','configs/mac-recipe-binding.json',m.node.path,'.runtime/bin/ffmpeg',...Object.values(m.interpreters),...Object.values(NATIVE.environments).map(v=>v.lock),...MODELS.filter(r=>r.origin==='app').map(r=>r.path)]){
    if(!expected.has(name))throw Error('Missing static inventory member: '+name);
  }
  if(expected.get(NATIVE.ffmpeg.path)?.sha256!==NATIVE.ffmpeg.sha256||expected.get(NATIVE.ffmpeg.path)?.bytes!==NATIVE.ffmpeg.sizeBytes)throw Error('FFmpeg/native binding differs');
  for(const env of Object.values(NATIVE.environments))if(expected.get(env.lock)?.sha256!==env.lockSha256)throw Error('Native environment lock differs');
  for(const model of MODELS.filter(r=>r.origin==='app'))if(expected.get(model.path)?.sha256!==model.sha256||expected.get(model.path)?.bytes!==model.sizeBytes)throw Error('Static model binding differs');
  if(m.recipeBindingPath!=='configs/mac-recipe-binding.json'||!hashValue(m.recipeBindingSha256))throw Error('Root descriptor path/SHA unresolved');
  const descriptor=jsonFile(physical(appRoot,m.recipeBindingPath,canonicalApp));
  if(descriptor.sha256!==m.recipeBindingSha256||expected.get(m.recipeBindingPath)?.sha256!==descriptor.sha256||!equal(descriptor.value,m.recipeBinding))throw Error('Root descriptor bytes/inventory differs');
  const rule=validateRecipeBinding(descriptor.value,expected);
  const original=jsonFile(physical(appRoot,rule.parent.path,canonicalApp));
  if(original.sha256!==rule.parent.sha256||m.originalRecipeSha256!==original.sha256)throw Error('Original Root recipe changed');
  if(expected.get(m.modelManifestPath).sha256!==rule.modelManifest.sha256)throw Error('Root model manifest binding differs');
  const derived=jsonFile(physical(appRoot,rule.derived.path,canonicalApp)),want=expectedMacRecipe(original.value,rule);
  if(!equal(derived.value,want)||derived.sha256!==rule.derived.sha256)throw Error('Scientific/Root derived recipe differs');
  return {appRoot,userRoot,canonicalApp,canonicalUser,m,expected,bundleSha256:bundleDocument.sha256,recipe:derived.value,derivedRecipeSha256:derived.sha256};
}
function modelLocations(binding){
  return Object.fromEntries(MODELS.map(row=>{
    if(row.origin!=='app')throw Error('Offline model must belong to immutable app');
    return [row.id,{spec:row,root:binding.appRoot,name:row.path,canonicalRoot:binding.canonicalApp}];
  }));
}
export function materializeMacRecipe(binding){
  const recipe=structuredClone(binding.recipe),origParent=path.posix.dirname(binding.m.recipePath),externalParent=path.join(binding.userRoot,'configs'),locations=modelLocations(binding);
  function mapped(value){
    if(typeof value!=='string'||path.isAbsolute(value)||value.includes('\\')||value.includes(':'))throw Error('Invalid original recipe address');
    const name=relativeName(path.posix.normalize(path.posix.join(origParent,value))),model=MODELS.find(r=>r.path===name);
    const target=model?path.join(locations[model.id].root,locations[model.id].name):path.join(binding.appRoot,name);
    if(!model&&!binding.expected.has(name))throw Error('Unbound recipe path');
    const relative=path.relative(externalParent,target).split(path.sep).join('/');
    if(path.isAbsolute(relative)||relative.includes(':')||relative.split('/').includes('work')||path.resolve(externalParent,relative)!==path.resolve(target))throw Error('Cannot satisfy unchanged config-relative asset resolver');
    const origin=binding.canonicalApp;
    const real=fs.realpathSync(target),rel=path.relative(origin,real);
    if(rel==='..'||rel.startsWith('../')||path.isAbsolute(rel))throw Error('Recipe mapping escapes selected origin');
    // Preserve venv interpreter address, even though containment checked separately.
    return relative;
  }
  for(const k of ['sciencePython','posePython','worker','sparseExtractor'])recipe[k]=mapped(recipe[k]);
  recipe.helpers=Object.fromEntries(Object.entries(recipe.helpers).map(([k,v])=>[k,mapped(v)]));
  for(const row of Object.values(recipe.models))row.path=mapped(row.path);
  for(const row of Object.values(recipe.checkpoints))row.path=mapped(row.path);
  recipe.ffmpeg.path=mapped(recipe.ffmpeg.path);
  for(const [name,digest] of Object.entries(recipe.inputSha256)){
    const logical=relativeName(path.posix.normalize(path.posix.join(origParent,name)));
    if(binding.expected.get(logical)?.sha256!==digest)throw Error('Recipe/static Source digest disagreement: '+logical);
  }
  recipe.inputSha256=Object.fromEntries(Object.entries(recipe.inputSha256).map(([k,v])=>[mapped(k),v]));
  for(const k of ['runtimeHashes','runtimeBytes'])recipe.backendSourceProvenance[k]=Object.fromEntries(Object.entries(recipe.backendSourceProvenance[k]).map(([p,v])=>[mapped(p),v]));
  return recipe;
}
export function requireMacDesktopReady(appRoot,userRoot){
  const binding=staticBinding(appRoot,userRoot);
  const receipt=jsonFile(physical(userRoot,'desktop/ready.json',binding.canonicalUser)).value;
  if(receipt.schemaVersion!==1||receipt.packageVersion!==VERSION||receipt.offline!==true||!equal(receipt.pythonVersions,PYTHON_VERSIONS)||receipt.bundleSha256!==binding.bundleSha256||receipt.nativeProfileSha256!==binding.m.nativeProfileSha256||receipt.appRoot!==appRoot||receipt.canonicalAppRoot!==binding.canonicalApp||receipt.userRoot!==userRoot||receipt.canonicalUserRoot!==binding.canonicalUser)throw Error('Stale receipt/header/root binding');
  if(!Array.isArray(receipt.files)||receipt.files.length!==binding.expected.size)throw Error('Receipt coverage differs');
  const names=new Set();
  for(const row of receipt.files){
    const name=relativeName(row.path),fold=name.toLowerCase();
    if(names.has(fold)||!binding.expected.has(name)||row.sha256!==binding.expected.get(name).sha256)throw Error('Receipt names/authoritative digests differ');
    names.add(fold);
  }
  // One fresh complete per-file physical pass; Python admission is not a witness.
  for(const row of receipt.files){
    const file=physical(appRoot,row.path,binding.canonicalApp),fresh=fingerprint(file),expected=binding.expected.get(row.path);
    if(fresh.bytes!==expected.bytes||!equal(fresh,Object.fromEntries(['dev','ino','bytes','mtimeNs','ctimeNs'].map(k=>[k,row[k]]))))throw Error('Ready static file changed: '+row.path);
  }
  if(!receipt.models||!equal(Object.keys(receipt.models).sort(),MODELS.map(r=>r.id).sort()))throw Error('Model roles differ');
  for(const [role,loc] of Object.entries(modelLocations(binding))){
    const r=receipt.models[role],p=physical(loc.root,loc.name,loc.canonicalRoot),fresh=fingerprint(p);
    if(r.absolutePath!==p||r.sha256!==loc.spec.sha256||r.bytes!==loc.spec.sizeBytes||r.origin!==loc.spec.origin||!equal(fresh,Object.fromEntries(['dev','ino','bytes','mtimeNs','ctimeNs'].map(k=>[k,r[k]]))))throw Error('Ready model map/metadata changed: '+role);
  }
  if(!hashValue(receipt.configSha256))throw Error('Invalid config generation checksum');
  const configName='configs/axel-release-ort4-macos-app-'+receipt.configSha256+'.json';
  if(receipt.configRelativePath!==configName||receipt.configPath!==path.join(userRoot,configName)||!Number.isSafeInteger(receipt.configBytes)||receipt.configBytes<=0)throw Error('Unconfined config generation selector');
  const configPath=physical(userRoot,configName,binding.canonicalUser),before=fingerprint(configPath),config=jsonFile(configPath);
  if(before.bytes!==receipt.configBytes||!equal(before,fingerprint(configPath))||receipt.configSha256!==config.sha256||!equal(config.value,materializeMacRecipe(binding)))throw Error('Selected config generation changed');
  return {...binding,receipt,configPath};
}
export function validateMacWebConfig(value,prepared){
  const c=value;
  if(!c||c.host!=='127.0.0.1'||!Number.isInteger(c.port)||c.port<1024||c.port>65535||!Number.isInteger(c.analysisPort)||c.analysisPort<1024||c.analysisPort>65535||c.port===c.analysisPort)throw Error('Explicit loopback web/API ports required');
  if(!Number.isInteger(c.maxWallSeconds)||c.maxWallSeconds<1||c.maxWallSeconds>5400)throw Error('Exact preserved max-wall binding unresolved');
  if(c.python!==prepared.sciencePython||c.dataDir!==path.join(prepared.userRoot,'web-data')||c.jobsDir!==path.join(prepared.userRoot,'jobs'))throw Error('External web data/jobs/science origins differ');
  return c;
}
export function writeMacWebGeneration(prepared,value){
  const c=validateMacWebConfig(value,prepared),body=Buffer.from(JSON.stringify(c,null,2)+'\n'),digest=sha(body);
  const name='configs/mac-desktop-web-'+digest+'.json',target=path.join(prepared.userRoot,name),parent=path.dirname(target);
  fs.mkdirSync(parent,{recursive:true});
  const realParent=fs.realpathSync(parent),rel=path.relative(prepared.admitted.canonicalUser,realParent);
  if(rel==='..'||rel.startsWith('../')||path.isAbsolute(rel)||fs.lstatSync(parent).isSymbolicLink())throw Error('Web generation escapes admitted user origin');
  if(fs.existsSync(target)){
    const actual=physical(prepared.userRoot,name,prepared.admitted.canonicalUser),read=jsonFile(actual);
    if(read.sha256!==digest||fs.statSync(actual).size!==body.length||!equal(read.value,c))throw Error('Existing web generation differs');
  }else{
    const temporary=path.join(parent,'.mac-web-'+process.pid+'-'+randomUUID()+'.tmp');
    const fd=fs.openSync(temporary,'wx',0o600);
    try{fs.writeFileSync(fd,body);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    try{try{fs.linkSync(temporary,target);}catch(e){if(e.code!=='EEXIST')throw e;const actual=physical(prepared.userRoot,name,prepared.admitted.canonicalUser);if(shaFile(actual)!==digest||fs.statSync(actual).size!==body.length)throw Error('Concurrent web generation differs');}}
    finally{fs.unlinkSync(temporary);}
  }
  return {path:target,relativePath:name,bytes:body.length,sha256:digest,value:c};
}
export function readMacWebGeneration(prepared,file){
  if(typeof file!=='string'||!path.isAbsolute(file))throw Error('Absolute explicit web config required');
  const name=path.relative(prepared.userRoot,file).split(path.sep).join('/');
  const match=/^configs\/mac-desktop-web-([a-f0-9]{64})\.json$/.exec(name);
  if(!match)throw Error('Unconfined web generation path');
  const actual=physical(prepared.userRoot,name,prepared.admitted.canonicalUser),before=fingerprint(actual),doc=jsonFile(actual);
  if(doc.sha256!==match[1]||!equal(before,fingerprint(actual)))throw Error('Web generation checksum changed');
  return validateMacWebConfig(doc.value,prepared);
}
export function prepareMacDesktopConfig(appRoot,userRoot){
  const admitted=requireMacDesktopReady(appRoot,userRoot);
  const prepared={appRoot,userRoot,configPath:admitted.configPath,sciencePython:physical(appRoot,admitted.m.interpreters.science,admitted.canonicalApp),posePython:physical(appRoot,admitted.m.interpreters.pose,admitted.canonicalApp),admitted};
  const c=admitted.m.desktopServerContract;
  if(!c||c.status!=='source-accepted'||!hashValue(c.webConfigSourceSha256)||typeof c.webConfigSourcePath!=='string')throw Error('Accepted immutable web template binding unresolved');
  const source=physical(appRoot,relativeName(c.webConfigSourcePath),admitted.canonicalApp),base=jsonFile(source);
  if(base.sha256!==c.webConfigSourceSha256||admitted.expected.get(c.webConfigSourcePath)?.sha256!==base.sha256)throw Error('Web template body/inventory binding differs');
  const web={...base.value,python:prepared.sciencePython,dataDir:path.join(userRoot,'web-data'),jobsDir:path.join(userRoot,'jobs')};
  prepared.webGeneration=writeMacWebGeneration(prepared,web);
  prepared.webConfigPath=prepared.webGeneration.path;
  return prepared;
}

function groupAlive(pgid){try{process.kill(-pgid,0);return true;}catch(e){if(e.code==='ESRCH')return false;throw e;}}
export class OwnedPhase{
  constructor(executable,argv,{onMessage=()=>{},streamCap=STREAM_CAP,env=process.env}={}){
    this.bytes=0;this.cancelled=false;this.shutdownAt=null;this.exit=null;this.stdoutEOF=false;this.stderrEOF=false;this.closed=false;this.problem=null;this.readyMessage=null;
    this.child=spawn(executable,argv,{stdio:['pipe','pipe','pipe'],detached:true,shell:false,env});
    this.pgid=this.child.pid??null;
    this.child.on('error',e=>{this.problem=e;});
    this.child.stdin.on('error',e=>{if(!['EPIPE','ECONNRESET'].includes(e.code))this.problem=e;});
    this.child.on('exit',(code,signal)=>{this.exit={code,signal};if(code!==0)this.problem??=Error('Owned phase exited unsuccessfully');});
    this.child.on('close',()=>{this.closed=true;});
    const decoders=[new TextDecoder('utf-8',{fatal:true}),new TextDecoder('utf-8',{fatal:true})];
    let pending='';
    for(const [i,stream] of [this.child.stdout,this.child.stderr].entries()){
      stream.on('data',chunk=>{
        this.bytes+=chunk.length;
        if(this.bytes>streamCap){this.problem=Error('Owned phase stream cap exceeded');this.requestStop();return;}
        try{
          const text=decoders[i].decode(chunk,{stream:true});
          if(i===0){pending+=text;if(pending.length>65536)throw Error('Owned JSONL frame too large');
            let cut;while((cut=pending.indexOf('\n'))>=0){const line=pending.slice(0,cut);pending=pending.slice(cut+1);if(!line)continue;
              const row=JSON.parse(line);if(!row||typeof row.type!=='string')throw Error('Invalid owned JSONL event');
              if(row.type==='ready'||row.type==='server-ready')this.readyMessage=row;
              onMessage(row);
            }
          }
        }catch(e){this.problem=e;this.requestStop();}
      });
      stream.on('error',e=>{this.problem=e;this.requestStop();});
      stream.on('end',()=>{
        try{decoders[i].decode();if(i===0&&pending)throw Error('Truncated owned JSONL frame');}
        catch(e){this.problem=e;}
        if(i===0)this.stdoutEOF=true;else this.stderrEOF=true;
      });
    }
  }
  requestStop(){
    this.cancelled=true;
    if(this.shutdownAt!==null)return;
    this.shutdownAt=performance.now();
    if(this.exit!==null)return;
    if(!this.child.stdin.destroyed){this.child.stdin.end(JSON.stringify({type:'shutdown'})+'\n');}
    // Private shutdown first. Group fallback is reserved for the original
    // close deadline so the Mac entry can close API/UI concurrently.
  }
  async closeWithin(ms){
    this.requestStop();const deadline=this.shutdownAt+ms;
    let term=false,kill=false;
    while(performance.now()<deadline){
      const alive=this.pgid!==null&&groupAlive(this.pgid);
      if(this.closed&&this.exit!==null&&this.stdoutEOF&&this.stderrEOF&&!alive)return {ownershipResolved:true,exit:this.exit};
      // Fallback only while the retained leader is unreaped and group live.
      // After leader exit, unresolved descendants cannot authorize a new signal
      // to a potentially reused PGID. Never renew shutdown origin.
      if(this.exit===null&&alive&&performance.now()>=deadline-1000&&!term){term=true;try{process.kill(-this.pgid,'SIGTERM');}catch(e){if(e.code!=='ESRCH')this.problem??=e;}}
      if(this.exit===null&&alive&&performance.now()>=deadline-500&&!kill){kill=true;try{process.kill(-this.pgid,'SIGKILL');}catch(e){if(e.code!=='ESRCH')this.problem??=e;}}
      await sleep(25);
    }
    return {ownershipResolved:false,exit:this.exit,problem:'Owned wait/EOF/group closure unresolved'};
  }
  async waitClean(ms){
    const deadline=performance.now()+ms;
    while(performance.now()<deadline){
      if(this.problem)throw this.problem;
      if(this.cancelled)throw Error('Owned phase cancelled before clean completion');
      if(this.closed&&this.exit!==null&&this.stdoutEOF&&this.stderrEOF&&(this.pgid===null||!groupAlive(this.pgid))){
        if(this.exit.code!==0)throw Error('Owned phase exited unsuccessfully');
        return;
      }
      await sleep(25);
    }
    throw Error('Owned phase exceeded original work deadline');
  }
}
export function attachMacDesktopControl(input,onShutdown){
  let pending='',bytes=0,stopped=false;
  const decoder=new TextDecoder('utf-8',{fatal:true});
  const stop=()=>{if(!stopped){stopped=true;onShutdown();}};
  const data=chunk=>{
    bytes+=chunk.length;if(bytes>65536){stop();return;}
    try{
      pending+=decoder.decode(chunk,{stream:true});
      let cut;while((cut=pending.indexOf('\n'))>=0){
        const line=pending.slice(0,cut);pending=pending.slice(cut+1);
        if(!line||JSON.parse(line).type!=='shutdown'){stop();return;}
        stop();
      }
    }catch{stop();}
  };
  input.on('data',data);input.on('end',stop);input.on('error',stop);
  return {get stopped(){return stopped;},detach(){input.off('data',data);input.off('end',stop);input.off('error',stop);}};
}
function loopback(url){
  const u=new URL(url);
  if(u.protocol!=='http:'||u.hostname!=='127.0.0.1'||u.username||u.password||!u.port)throw Error('Expected bound loopback URL');
  return u;
}
function strictHealth(url){
  loopback(url);
  return new Promise((resolve,reject)=>{
    const req=http.get(url,res=>{let bytes=0,body='';
      if(res.statusCode!==200){res.resume();reject(Error('HTTP not ready'));return;}
      res.setEncoding('utf8');res.on('data',s=>{bytes+=Buffer.byteLength(s);if(bytes>65536){req.destroy();reject(Error('Health response cap exceeded'));return;}body+=s;});
      res.on('end',()=>{try{const v=JSON.parse(body);if(v.status!=='ready'||v.inferenceAvailable!==true||v.activeJobId!==null)throw Error('Strict analysis health not ready/idle');resolve(v);}catch(e){reject(e);}});
      res.on('error',reject);
    });
    req.setTimeout(1000,()=>req.destroy(Error('Health request deadline')));req.on('error',reject);
  });
}
export function serverBinding(prepared){
  const c=prepared.admitted.m.desktopServerContract;
  if(!c||c.status!=='source-accepted'||c.entry!=='scripts/start-macos-desktop.mjs'||!hashValue(c.sourceSha256)||!Number.isSafeInteger(c.entryBytes)||c.entryBytes<=0
      ||c.recipeEnvironmentVariable!=='FS_ELEM_MAC_RECIPE'||c.userRootEnvironmentVariable!=='FS_ELEM_MAC_USER_ROOT'||c.webConfigEnvironmentVariable!=='FS_ELEM_MAC_WEB_CONFIG'||c.readyEventType!=='ready'||!equal(c.argv,[])
      ||!equal(c.control,{wire:'JSONL',shutdown:{type:'shutdown'},eof:'shutdown'})
      ||!equal(c.healthRequirements,{status:'ready',inferenceAvailable:true,activeJobId:null}))throw Error('Accepted new Mac entry contract unresolved/different');
  const entry=physical(prepared.appRoot,c.entry,prepared.admitted.canonicalApp),row=prepared.admitted.expected.get(c.entry);
  if(row?.sha256!==c.sourceSha256||row?.bytes!==c.entryBytes||fs.statSync(entry).size!==c.entryBytes||shaFile(entry)!==c.sourceSha256)throw Error('New Mac entry bytes/SHA/inventory differs');
  const web=prepared.webGeneration.value;
  const ui='http://127.0.0.1:'+web.port+'/analysis',health='http://127.0.0.1:'+web.port+'/api/analysis/health';
  if(c.uiUrl!==ui||c.healthUrl!==health)throw Error('Bound web template and exact health/UI URLs differ');
  loopback(c.healthUrl);loopback(c.uiUrl);
  return {c,entry,env:{...process.env,FS_ELEM_MAC_RECIPE:prepared.configPath,FS_ELEM_MAC_USER_ROOT:prepared.userRoot,FS_ELEM_MAC_WEB_CONFIG:prepared.webConfigPath}};
}
export function assertMacReadyContext(phase,{deadline,currentPhase,isStopping}){
  if(performance.now()>=deadline)throw Error('Original backend ready deadline exceeded');
  if(currentPhase()!==phase)throw Error('Retained backend phase identity changed');
  if(isStopping())throw Error('Parent/control stopped before public ready');
  if(phase.problem)throw phase.problem;
  if(phase.exit!==null||phase.closed)throw Error('Backend exited before public ready');
}
function strictUI(url){
  loopback(url);
  return new Promise((resolve,reject)=>{
    const req=http.get(url,res=>{let bytes=0;
      if(res.statusCode!==200||!String(res.headers['content-type']??'').includes('text/html')){res.resume();reject(Error('Exact UI route not ready'));return;}
      res.on('data',b=>{bytes+=b.length;if(bytes>2*1024*1024){req.destroy(Error('UI response cap exceeded'));}});
      res.on('end',()=>resolve());res.on('error',reject);
    });
    req.setTimeout(1000,()=>req.destroy(Error('UI request deadline')));req.on('error',reject);
  });
}
export async function waitMacReadiness(phase,contract,context,{healthProbe=strictHealth,uiProbe=strictUI}={}){
  while(performance.now()<context.deadline){
    assertMacReadyContext(phase,context);
    if(phase.readyMessage?.type===contract.readyEventType&&phase.readyMessage.url===contract.uiUrl){
      try{await healthProbe(contract.healthUrl);}catch{assertMacReadyContext(phase,context);await sleep(100);continue;}
      assertMacReadyContext(phase,context);
      try{await uiProbe(contract.uiUrl);}catch{assertMacReadyContext(phase,context);await sleep(100);continue;}
      assertMacReadyContext(phase,context);
      return;
    }
    await sleep(100);
  }
  assertMacReadyContext(phase,context);
  throw Error('Strict owned backend readiness not reached');
}
export function unexpectedBackendFailure(phase,stopping){
  if(phase.problem)return phase.problem;
  if(phase.exit!==null&&(!stopping||phase.exit.code!==0))return Error('Unexpected backend completion: '+String(phase.exit.code??phase.exit.signal));
  return null;
}

export function assertMacBackendCompletion(retainedPhase,currentPhase,closed,firstFailure=null){
  // Preserve any earlier cause, then admit the CURRENT outcome of the SAME
  // retained phase after its awaited cleanup and before stopped/success.
  if(firstFailure)throw firstFailure;
  if(currentPhase!==retainedPhase)throw Error('Retained backend changed during cleanup');
  if(retainedPhase.problem)throw retainedPhase.problem;
  if(!closed.ownershipResolved)throw Error(closed.problem??'Backend ownership unresolved');
  if(closed.exit?.code!==0||retainedPhase.exit?.code!==0)throw Error('Backend stopped with failure after cleanup');
}

export async function runMacDesktop(appRoot,userRoot,{input=process.stdin,output=process.stdout}={}){
  let streamBytes=0,phase=null,phaseKind=null,stopping=false,unresolved=false;
  const emit=row=>{const wire=JSON.stringify(row)+'\n';streamBytes+=Buffer.byteLength(wire);if(streamBytes>STREAM_CAP)throw Error('Supervisor stream cap exceeded');output.write(wire);};
  const control=attachMacDesktopControl(input,()=>{stopping=true;phase?.requestStop();});
  const stopSignal=()=>{stopping=true;phase?.requestStop();};process.on('SIGTERM',stopSignal);process.on('SIGINT',stopSignal);
  try{
    if(process.platform!=='darwin'||process.arch!=='arm64')throw Error('Requires macOS Apple Silicon');
    if(!path.isAbsolute(appRoot)||!path.isAbsolute(userRoot))throw Error('Absolute app/user roots required');
    const canonicalApp=fs.realpathSync(appRoot);
    const document=jsonFile(physical(appRoot,META,canonicalApp)).value;
    // Unknown exact runtime/version is a failure, not a bootstrap bypass.
    if(document.node?.path!=='.runtime/bin/node'||document.node.version!==process.versions.node||document.node.major!==22||document.node.version!=='22.23.3')throw Error('Bundled Node version differs/unbound');
    if(!equal(document.interpreters,{science:'.runtime/venv-science/bin/python',pose:'.runtime/venv-pose/bin/python'}))throw Error('Science/pose paths unresolved');
    if(!Array.isArray(document.files)||document.schemaVersion!==1||document.packageVersion!==VERSION||document.platformId!=='macos-arm64'||document.offline!==true||!equal(document.pythonVersions,PYTHON_VERSIONS))throw Error('Bootstrap inventory binding missing');
    const criticalNames=[document.node.path,document.interpreters.science,'scripts/macos-first-run.py'];
    const critical=new Map(),criticalFolded=new Set();
    for(const row of document.files){relativeName(row.path);if(criticalFolded.has(row.path.toLowerCase())||!hashValue(row.sha256)||!Number.isSafeInteger(row.bytes)||row.bytes<0)throw Error('Bootstrap inventory invalid');critical.set(row.path,row);criticalFolded.add(row.path.toLowerCase());}
    for(const name of criticalNames){const row=critical.get(name);if(!row)throw Error('Bootstrap executable absent from inventory');const file=physical(appRoot,name,canonicalApp),before=fingerprint(file);
      if(before.bytes!==row.bytes||shaFile(file)!==row.sha256||!equal(before,fingerprint(file)))throw Error('Bootstrap executable checksum changed');
    }
    if(fs.realpathSync(process.execPath)!==fs.realpathSync(physical(appRoot,document.node.path,canonicalApp)))throw Error('Controller interpreter not bundled Node');
    const python=physical(appRoot,document.interpreters.science,canonicalApp),entry=physical(appRoot,'scripts/macos-first-run.py',canonicalApp);
    phaseKind='bootstrap';phase=new OwnedPhase(python,['-B',entry,'--app-root',appRoot,'--user-root',userRoot],{onMessage:row=>{if(row.type==='progress')emit(row);else if(row.type==='error')throw Error(row.message??'Bootstrap failed');}});
    await phase.waitClean(600000);
    // Child exit/EOF/group gone precedes independent receipt admission.
    phase=null;if(stopping)throw Error('Parent/control stopped before ready');
    const prepared=prepareMacDesktopConfig(appRoot,userRoot),server=serverBinding(prepared);
    phaseKind='backend';phase=new OwnedPhase(process.execPath,[server.entry,...server.c.argv],{env:server.env,onMessage:row=>{if(row.type==='progress')emit(row);}});
    const readyPhase=phase,deadline=performance.now()+90000;
    const readyContext={deadline,currentPhase:()=>phase,isStopping:()=>stopping};
    await waitMacReadiness(readyPhase,server.c,readyContext);
    assertMacReadyContext(readyPhase,readyContext); // Immediately before public ready.
    emit({type:'ready',url:server.c.uiUrl});
    while(!stopping&&phase.exit===null){if(phase.problem)throw phase.problem;await sleep(100);}
    const closingPhase=phase,failure=unexpectedBackendFailure(closingPhase,stopping);
    const closed=await closingPhase.closeWithin(29000);
    if(!closed.ownershipResolved){unresolved=true;throw Error(closed.problem);}
    assertMacBackendCompletion(closingPhase,phase,closed,failure);
    phase=null;phaseKind=null;
    emit({type:'stopped',ownershipResolved:true});return 0;
  }catch(e){
    if(phase){const closed=await phase.closeWithin(phaseKind==='backend'?29000:10000);unresolved=!closed.ownershipResolved;}
    try{emit({type:'error',message:String(e.message??e),ownershipResolved:!unresolved});}catch{}
    if(unresolved){
      // Keep controller generation alive; never offer retry/stopped while any
      // owned phase remains unresolved. No post-reap signalling of reused PGID.
      await new Promise(()=>{setInterval(()=>{},1000);});
    }
    return 1;
  }finally{
    control.detach();process.off('SIGTERM',stopSignal);process.off('SIGINT',stopSignal);
  }
}
async function main(){
  const args=process.argv.slice(2);
  if(args.length!==4||args[0]!=='--app-root'||args[2]!=='--user-root')throw Error('Usage: --app-root ABS --user-root ABS');
  process.exitCode=await runMacDesktop(args[1],args[3]);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  main().catch(e=>{process.stdout.write(JSON.stringify({type:'error',message:String(e.message??e),ownershipResolved:true})+'\n');process.exitCode=1;});
}
