import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {join} from 'node:path';
import {loadConfig,projectRoot} from './config.mjs';
import {openStore} from '../server/store.mjs';
const children=[];let stopping=false;
async function stop(code=0) {
  if(stopping)return;stopping=true;
  await Promise.all(children.map(async child=>{
    if(!child.pid || child.exitCode!==null || child.signalCode!==null)return;
    const ended=once(child,'exit');child.kill('SIGTERM');
    const timer=setTimeout(()=>child.kill('SIGKILL'),3000);
    await ended;clearTimeout(timer);
  }));
  process.exit(code);
}
process.on('SIGINT',()=>stop());process.on('SIGTERM',()=>stop());
function ready(child,event,accept) {
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Service readiness timed out')),15000);
    const fail=()=>{clearTimeout(timer);reject(Error('Service failed to start'))};
    child.once('error',fail);child.once('exit',fail);
    event(value=>{
      try {if(!accept(value))return;clearTimeout(timer);child.off('error',fail);child.off('exit',fail);resolve();}
      catch(e){clearTimeout(timer);reject(e);}
    });
  });
}
function watch(child) {child.on('exit',()=>{if(!stopping){console.error('Один из сервисов остановился.');stop(1)}});}
try {
  const args=process.argv.slice(2);
  if(args.length && (args.length!==2 || args[0]!=='--config'))throw Error('Usage: node scripts/start.mjs [--config path]');
  const config=loadConfig(projectRoot,args[1]);
  const store=openStore(config.dataDir);store.close();
  const analysis=spawn(config.python,[join(projectRoot,'services/analysis/server.py'),'--port',String(config.analysisPort)],{stdio:['ignore','pipe','inherit']});children.push(analysis);
  const lines=createInterface({input:analysis.stdout});
  await ready(analysis,listener=>lines.on('line',listener),line=>JSON.parse(line).port===config.analysisPort);watch(analysis);
  const web=spawn(process.execPath,[join(projectRoot,'scripts/web-worker.mjs'),...(args[1]?[args[1]]:[])],{cwd:join(projectRoot,'apps/web'),stdio:['ignore','inherit','inherit','ipc']});children.push(web);
  await ready(web,listener=>web.on('message',listener),message=>message.ready===true);watch(web);
  console.log(`FS_elem готов: http://${config.host}:${config.port}`);
  console.log('Для остановки нажмите Ctrl+C.');
} catch(e) {console.error(e.message);await stop(1);}
