import {statSync,createReadStream} from 'node:fs';
import {request as httpRequest} from 'node:http';
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
      if(path.startsWith('/api/analysis/')) {
        const fail=(status,code,message)=>send(status,{error:{code,message}});
        if(!analysisPort)return fail(503,'SERVICE_UNAVAILABLE','Analysis service unavailable');
        if(req.headers['sec-fetch-site']==='cross-site' || (req.headers.origin && req.headers.origin!==`http://${req.headers.host}`))return fail(403,'ORIGIN_REJECTED','Origin rejected');
        const route=path==='/api/analysis/health'?'/health':path.slice('/api/analysis'.length);
        if(route!=='/health' && !/^\/jobs(?:\/[a-z0-9-]+(?:\/(?:state|result|pose|media))?)?$/.test(route))return fail(404,'NOT_FOUND','Not found');
        if(!['GET','HEAD','POST','DELETE'].includes(req.method))return fail(405,'METHOD_NOT_ALLOWED','Method not allowed');
        const declared=req.headers['content-length'];
        if(declared && (!/^\d+$/.test(declared) || Number(declared)>512*1024*1024))return fail(413,'TOO_LARGE','Maximum video size is 512 MiB');
        const headers={};
        for(const name of ['content-type','content-length','x-filename','range'])if(req.headers[name])headers[name]=req.headers[name];
        // Stream raw bytes and ranged media; never buffer an entire video in Node.
        const upstream=httpRequest({hostname:'127.0.0.1',port:analysisPort,path:route,method:req.method,headers},response=>{
          const forwarded={};
          for(const name of ['content-type','content-length','content-range','accept-ranges','cache-control'])if(response.headers[name])forwarded[name]=response.headers[name];
          res.writeHead(response.statusCode||502,forwarded);response.on('error',()=>res.destroy());response.pipe(res);
        });
        upstream.setTimeout(120000,()=>upstream.destroy(Error('Analysis service timed out')));
        upstream.on('error',()=>{if(res.headersSent)res.destroy();else fail(503,'SERVICE_UNAVAILABLE','Analysis service unavailable');});
        req.on('aborted',()=>upstream.destroy());res.on('close',()=>{if(!res.writableFinished)upstream.destroy();});
        req.pipe(upstream);return;
      }
      if(req.method==='GET' && path==='/api/health') return send(200,{app:'fs-elem',schemaVersion:2,status:'ready'});
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
