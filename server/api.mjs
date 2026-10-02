import {statSync,createReadStream} from 'node:fs';
export function parseRange(header,size) {
  const m=/^bytes=(\d*)-(\d*)$/.exec(header||'');
  if(!m || (!m[1]&&!m[2])) throw Error('Invalid range');
  const start=m[1]?Number(m[1]):Math.max(0,size-Number(m[2]));
  const end=m[1]?(m[2]?Math.min(Number(m[2]),size-1):size-1):size-1;
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=size||start>end||start<0) throw Error('Invalid range');
  return [start,end];
}
export function createApi(store,{analysisPort}={}) {
  return async(req,res,next)=>{
    const send=(status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
    try {
      const path=new URL(req.url,'http://localhost').pathname;
      if(!path.startsWith('/api/')&&!path.startsWith('/media/')) return next();
      const port=req.socket.localPort;
      if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(req.headers.host)) return send(403,{error:'Local access only'});
      if(req.method==='GET' && path==='/api/health') return send(200,{app:'fs-elem',schemaVersion:2,status:'ready'});
      if(req.method==='GET' && path==='/api/analysis/health') {
        if(!analysisPort) return send(503,{error:'Analysis service unavailable'});
        const r=await fetch(`http://127.0.0.1:${analysisPort}/health`,{signal:AbortSignal.timeout(2000)});return send(r.status,await r.json());
      }
      if(req.method==='GET' && path==='/api/catalog') return send(200,store.catalog());
      if(req.method==='GET' && path==='/api/annotations') return send(200,store.read());
      if(req.method==='PUT' && path==='/api/annotations') {
        if(req.headers.origin!==`http://${req.headers.host}`) return send(403,{error:'Origin rejected'});
        const chunks=[];let length=0;
        for await(const chunk of req) {length+=chunk.length;if(length>2_000_000)return send(413,{error:'Too large'});chunks.push(chunk);}
        return send(200,store.save(JSON.parse(Buffer.concat(chunks).toString('utf8'))));
      }
      if(req.method==='GET' && path.startsWith('/api/frames/')) {
        const frames=store.frames(path.slice('/api/frames/'.length));
        return frames?send(200,frames):send(404,{error:'Нет видео'});
      }
      if(['GET','HEAD'].includes(req.method) && path.startsWith('/media/')) {
        const file=store.media(path.slice('/media/'.length));if(!file)return send(404,{error:'Нет видео'});
        const size=statSync(file).size;let start=0,end=size-1,status=200;
        if(req.headers.range) {
          try {[start,end]=parseRange(req.headers.range,size);status=206;}
          catch {res.writeHead(416,{'Content-Range':`bytes */${size}`});return res.end();}
        }
        const headers={'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Length':end-start+1};
        if(status===206)headers['Content-Range']=`bytes ${start}-${end}/${size}`;
        res.writeHead(status,headers);if(req.method==='HEAD')return res.end();
        const stream=createReadStream(file,{start,end});stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);return;
      }
      return send(404,{error:'Не найдено'});
    } catch(e) {
      if(res.headersSent)res.destroy();else send(e.status||400,{error:e.message||'Ошибка'});
    }
  };
}
