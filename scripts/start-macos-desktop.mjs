// Narrow Mac-only entry. Existing Windows entry and common runtime are untouched.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {prepareMacDesktopConfig,readMacWebGeneration,validateMacWebConfig,attachMacDesktopControl} from './macos-bundle.mjs';

const STREAM_CAP=262144,FRAME_CAP=65536,API_GRACE=24000,UI_GRACE=4000,FALLBACK=3000;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function regular(p){if(!fs.lstatSync(p).isFile()||fs.lstatSync(p).isSymbolicLink())throw Error('Required regular entry asset');return p;}
export function macServicePlan(appRoot,prepared,config,env){
  const userRoot=env.FS_ELEM_MAC_USER_ROOT,recipe=env.FS_ELEM_MAC_RECIPE,webFile=env.FS_ELEM_MAC_WEB_CONFIG;
  if(typeof userRoot!=='string'||!path.isAbsolute(userRoot)||typeof recipe!=='string'||!path.isAbsolute(recipe)||typeof webFile!=='string'||!path.isAbsolute(webFile))throw Error('Explicit Mac recipe/userRoot/web-config interface required');
  if(prepared.appRoot!==appRoot||userRoot!==prepared.userRoot||recipe!==prepared.configPath||webFile!==prepared.webConfigPath)throw Error('Selected receipt generation and explicit Mac environment differ');
  validateMacWebConfig(config,prepared);
  return {prepared,config,recipe,webFile,userRoot,
    analysis:{executable:prepared.sciencePython,argv:[regular(path.join(appRoot,'services/analysis/server.py')),'--port',String(config.analysisPort),'--config',recipe,'--jobs',config.jobsDir,'--max-wall-seconds',String(config.maxWallSeconds)],cwd:appRoot,
      env:{...env,FS_ELEM_CONTROL_STDIN:'1',PYTHONIOENCODING:'utf-8',PYTHONUTF8:'1'}},
    web:{executable:process.execPath,argv:[regular(path.join(appRoot,'scripts/release-owned-web-worker.mjs')),webFile],cwd:path.join(appRoot,'apps/web'),env:{...env}},
    url:'http://127.0.0.1:'+config.port+'/analysis',
    healthUrl:'http://127.0.0.1:'+config.port+'/api/analysis/health'};
}
export function loadMacEntryPlan(appRoot,env=process.env){
  const userRoot=env.FS_ELEM_MAC_USER_ROOT;
  if(typeof userRoot!=='string'||!path.isAbsolute(userRoot)||typeof env.FS_ELEM_MAC_RECIPE!=='string'||!path.isAbsolute(env.FS_ELEM_MAC_RECIPE)||typeof env.FS_ELEM_MAC_WEB_CONFIG!=='string'||!path.isAbsolute(env.FS_ELEM_MAC_WEB_CONFIG))throw Error('Explicit Mac recipe/userRoot/web-config interface required');
  const prepared=prepareMacDesktopConfig(appRoot,userRoot);
  return macServicePlan(appRoot,prepared,readMacWebGeneration(prepared,env.FS_ELEM_MAC_WEB_CONFIG),env);
}
export class MacService{
  constructor(kind,plan,notify,consume){
    this.kind=kind;this.exit=null;this.closed=false;this.stdoutEOF=false;this.stderrEOF=false;this.ready=false;this.problem=null;this.shutdownAt=null;
    this.child=spawn(plan.executable,plan.argv,{cwd:plan.cwd,env:plan.env,shell:false,detached:false,
      stdio:kind==='web'?['ignore','pipe','pipe','ipc']:['pipe','pipe','pipe']});
    this.child.on('error',e=>{this.problem??=e;notify(e);});
    this.child.stdin?.on('error',e=>{if(!['EPIPE','ECONNRESET'].includes(e.code)){this.problem??=e;notify(e);}});
    this.child.on('exit',(code,signal)=>{this.exit={code,signal};if(this.shutdownAt===null){const e=Error(kind+' service exited unexpectedly: '+String(code??signal));this.problem??=e;notify(e);}});
    this.child.on('close',()=>{this.closed=true;});
    if(kind==='web'){
      this.child.on('message',row=>{
        try{consume(Buffer.byteLength(JSON.stringify(row)));
          if(row?.ready===true){if(row.port!==plan.port||row.mode!=='production')throw Error('Owned web ready port/mode mismatch');this.ready=true;}
        }catch(e){this.problem??=e;notify(e);}
      });
      this.child.on('disconnect',()=>{if(this.shutdownAt===null&&!this.closed){const e=Error('Owned web IPC disappeared');this.problem??=e;notify(e);}});
    }
    const decoders=[new TextDecoder('utf-8',{fatal:true}),new TextDecoder('utf-8',{fatal:true})];
    let lines='';
    for(const [i,stream] of [this.child.stdout,this.child.stderr].entries()){
      stream.on('data',chunk=>{
        try{consume(chunk.length);const text=decoders[i].decode(chunk,{stream:true});
          if(i===0&&kind==='analysis'){
            lines+=text;if(Buffer.byteLength(lines)>FRAME_CAP)throw Error('Analysis ready frame exceeds cap');
            let cut;while((cut=lines.indexOf('\n'))>=0){const line=lines.slice(0,cut);lines=lines.slice(cut+1);if(!line)continue;
              const row=JSON.parse(line);if(row?.port!==undefined){if(row.port!==plan.port)throw Error('Analysis ready port mismatch');this.ready=true;}
            }
          }
        }catch(e){this.problem??=e;notify(e);}
      });
      stream.on('error',e=>{this.problem??=e;notify(e);});
      stream.on('end',()=>{
        try{decoders[i].decode();if(i===0&&kind==='analysis'&&lines)throw Error('Truncated analysis protocol');}
        catch(e){this.problem??=e;notify(e);}
        if(i===0)this.stdoutEOF=true;else this.stderrEOF=true;
      });
    }
  }
  async waitReady(ms,stopped){
    const deadline=performance.now()+ms;
    while(performance.now()<deadline){
      if(stopped())throw Error('Mac parent/control stopped startup');
      if(this.problem)throw this.problem;
      if(this.exit!==null)throw Error(this.kind+' exited before ready');
      if(this.ready)return;
      await sleep(25);
    }
    throw Error(this.kind+' startup exceeded its original deadline');
  }
  requestStop(origin){
    if(this.shutdownAt!==null)return;
    this.shutdownAt=origin;
    if(this.exit!==null)return;
    if(this.kind==='analysis'){
      if(!this.child.stdin.destroyed)this.child.stdin.end(JSON.stringify({type:'shutdown'})+'\n');
    }else if(this.child.connected){
      this.child.send({type:'shutdown'},error=>{
        if(error&&!['EPIPE','ERR_IPC_CHANNEL_CLOSED'].includes(error.code))this.problem??=error;
        if(this.child.connected)this.child.disconnect();
      });
    }
  }
  async closeFrom(origin,grace){
    this.requestStop(origin);
    const gracefulDeadline=origin+grace,finalDeadline=gracefulDeadline+FALLBACK;
    let term=false,kill=false;
    while(performance.now()<finalDeadline){
      if(this.closed&&this.exit!==null&&this.stdoutEOF&&this.stderrEOF)return {closed:true,exit:this.exit,problem:this.problem};
      if(this.exit===null&&performance.now()>=gracefulDeadline&&!term){term=true;this.child.kill('SIGTERM');}
      if(this.exit===null&&performance.now()>=finalDeadline-500&&!kill){kill=true;this.child.kill('SIGKILL');}
      await sleep(25);
    }
    return {closed:false,exit:this.exit,problem:this.problem??Error(this.kind+' wait/EOF closure unresolved')};
  }
}
export async function runMacEntry(appRoot,{env=process.env,input=process.stdin,output=process.stdout}={}){
  let stopped=false,origin=null,firstError=null,analysis=null,web=null,bytes=0,wireBytes=0;
  const emit=row=>{const wire=JSON.stringify(row)+'\n';wireBytes+=Buffer.byteLength(wire);if(wireBytes>STREAM_CAP)throw Error('Mac entry output cap exceeded');output.write(wire);};
  const stop=()=>{stopped=true;origin??=performance.now();analysis?.requestStop(origin);web?.requestStop(origin);};
  const fail=error=>{firstError??=error;stop();};
  const consume=n=>{bytes+=n;if(bytes>STREAM_CAP)throw Error('Combined owned service streams exceed cap');};
  const control=attachMacDesktopControl(input,stop);
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
  try{
    if(process.platform!=='darwin'||process.arch!=='arm64')throw Error('Mac desktop requires Apple Silicon');
    if(process.versions.node!=='22.23.3')throw Error('Mac desktop requires bundled Node22.23.3');
    if(process.argv.length!==2)throw Error('Mac entry uses explicit environment only; no legacy CLI flags');
    const plan=loadMacEntryPlan(appRoot,env);
    if(fs.realpathSync(process.execPath)!==fs.realpathSync(path.join(appRoot,'.runtime/bin/node')))throw Error('Mac entry interpreter is not admitted bundled Node');
    for(const dir of [plan.config.dataDir,plan.config.jobsDir])fs.mkdirSync(dir,{recursive:true});
    emit({type:'progress',stage:'analysis_service'});
    analysis=new MacService('analysis',{...plan.analysis,port:plan.config.analysisPort},fail,consume);
    await analysis.waitReady(15000,()=>stopped);
    emit({type:'progress',stage:'web_service'});
    web=new MacService('web',{...plan.web,port:plan.config.port},fail,consume);
    await web.waitReady(15000,()=>stopped);
    if(stopped||firstError||analysis.exit!==null||analysis.problem||web.exit!==null||web.problem)throw firstError??Error('Owned services changed before private ready');
    // Private service-port/IPC event only. The outer supervisor alone verifies
    // fresh strict HTTP health/UI and emits public desktop readiness.
    emit({type:'ready',url:plan.url,profile:'ort4',qualification:'owned-service-port-and-web-ipc-only'});
    while(!stopped){await sleep(100);}
  }catch(e){firstError??=e;stop();}
  // API and UI grace periods share ONE shutdown origin and run concurrently.
  origin??=performance.now();stopped=true;
  const results=await Promise.all([
    analysis?analysis.closeFrom(origin,API_GRACE):Promise.resolve({closed:true,exit:{code:0}}),
    web?web.closeFrom(origin,UI_GRACE):Promise.resolve({closed:true,exit:{code:0}})
  ]);
  const unresolved=results.some(r=>!r.closed);
  for(const r of results){if(r.problem)firstError??=r.problem;if(r.exit&&r.exit.code!==0)firstError??=Error('Owned service shutdown failed: '+String(r.exit.code??r.exit.signal));}
  try{
    if(firstError)emit({type:'error',stage:'services',message:String(firstError.message??firstError),ownershipResolved:!unresolved});
    if(!unresolved)emit({type:'stopped',exitCode:firstError?1:0,ownershipResolved:true});
  }catch(e){firstError??=e;}
  if(unresolved){
    // Do not announce stopped or let the retained controller be retried while
    // service wait/stream closure is unknown. Outer owned-group cleanup applies.
    await new Promise(()=>{setInterval(()=>{},1000);});
  }
  control.detach();process.off('SIGINT',stop);process.off('SIGTERM',stop);
  return firstError?1:0;
}
async function main(){const appRoot=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');process.exitCode=await runMacEntry(appRoot);}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  main().catch(e=>{process.stdout.write(JSON.stringify({type:'error',stage:'entry',message:String(e.message??e),ownershipResolved:false})+'\n');process.exitCode=1;});
}
