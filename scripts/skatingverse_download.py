"""Bounded research-only SkatingVerse intake; HTTP ranges, CRC, original train split."""
import argparse,collections,hashlib,json,struct,threading,urllib.request,zipfile,io,zlib
from pathlib import Path,PurePosixPath
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1]
API='https://modelscope.cn/api/v1/datasets/awei2003/1st_SkatingVerse_Dataset/oss/tree/?MaxLimit=100&Revision=master&Recursive=true&FilterDir=true'
ARCHIVE='1st_SkatingVerse_Challenge_Dataset_train_test_videos.zip'
# 210 fixed examples. Include both Axel counts and all five alternative jump families.
QUOTAS={21:30,2:40,9:30,0:15,8:15,1:15,10:15,11:15,27:20,3:5,4:5,5:5}
def safe_name(name):
 p=PurePosixPath(name)
 if len(p.parts)!=2 or p.parts[0]!='train_videos' or p.suffix!='.mp4' or '..' in p.parts:raise ValueError('unsafe/non-training member')
 return p.name
def select_members(rows,quotas,cap):
 result=[]
 for label,count in sorted(quotas.items()):
  groups=collections.defaultdict(list)
  for r in sorted(rows,key=lambda x:hashlib.sha256(x['name'].encode()).hexdigest()):
   if r['label']==label:groups[r['group']].append(r)
  chosen=[]
  while len(chosen)<count:
   progressed=False
   for group in sorted(groups,key=lambda x:hashlib.sha256(x.encode()).hexdigest()):
    if groups[group] and len(chosen)<count:chosen.append(groups[group].pop(0));progressed=True
   if not progressed:raise ValueError('insufficient class examples')
  result.extend(chosen)
 if sum(r['compressed'] for r in result)>cap:raise ValueError('selection exceeds cap')
 return result
class Budget:
 def __init__(self,cap):self.cap=cap;self.bytes=0;self.lock=threading.Lock()
 def reserve(self,n):
  with self.lock:
   if self.bytes+n>self.cap:raise ValueError('network byte cap exceeded')
   self.bytes+=n
class Remote(io.RawIOBase):
 def __init__(self,url,size,budget):self.url=url;self.size=size;self.pos=0;self.budget=budget
 def seekable(self):return True
 def seek(self,offset,whence=0):
  self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset
  if self.pos<0:raise ValueError('negative seek')
  return self.pos
 def tell(self):return self.pos
 def read(self,n=-1):
  n=self.size-self.pos if n<0 else min(n,self.size-self.pos)
  if n==0:return b''
  if n>8_000_000:raise ValueError('oversized single range')
  start=self.pos;end=start+n-1;self.budget.reserve(n)
  with urllib.request.urlopen(urllib.request.Request(self.url,headers={'Range':f'bytes={start}-{end}'}),timeout=90) as r:
   if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {start}-{end}/{self.size}':raise ValueError('server ignored range')
   data=r.read(n+1)
  if len(data)!=n:raise ValueError('incorrect range length')
  self.pos+=n;return data
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'data/skatingverse-pilot-v1');args=parser.parse_args()
 out=args.output;out.mkdir(parents=True,exist_ok=True);(out/'clips').mkdir(exist_ok=True)
 budget=Budget(300_000_000)
 with urllib.request.urlopen(API,timeout=30) as r:objects={x['Key']:x for x in json.load(r)['Data']}
 hashes={};texts={}
 for name in ['train.txt','mapping.txt']:
  with urllib.request.urlopen(objects[name]['Url'],timeout=30) as r:data=r.read(1_000_000)
  budget.reserve(len(data));(out/name).write_bytes(data);hashes[name]=hashlib.sha256(data).hexdigest();texts[name]=data.decode()
 labels={name:int(label) for name,label in (x.split() for x in texts['train.txt'].splitlines())}
 archive=objects[ARCHIVE];remote=Remote(archive['Url'],archive['Size'],budget)
 with zipfile.ZipFile(remote) as z:infos=z.infolist()
 rows=[]
 for info in infos:
  if not info.filename.startswith('train_videos/') or not info.filename.endswith('.mp4'):continue
  name=safe_name(info.filename);stem=Path(name).stem
  if stem not in labels:raise ValueError('unlabeled training member')
  rows.append(dict(name=info.filename,label=labels[stem],group=stem.split('_')[0],siblingGroup=stem.removesuffix('_sub'),compressed=info.compress_size,size=info.file_size,offset=info.header_offset,crc32=info.CRC,method=info.compress_type))
 chosen=select_members(rows,QUOTAS,250_000_000)
 manifest=dict(schemaVersion=1,source='SkatingVerse official ModelScope',license='other; terms unspecified; research intake only, not for redistribution',originalSplit='train',grouping='numeric filename prefix conservatively grouped; semantics unverified; sibling stem retained',archiveSize=archive['Size'],sourceMetadataSha256=hashes,quotas=QUOTAS,items=chosen)
 (out/'selection.json').write_text(json.dumps(manifest,indent=2))
 print('SELECTED',len(chosen),'compressed bytes',sum(x['compressed'] for x in chosen),flush=True)
 def download(item):
  target=out/'clips'/safe_name(item['name'])
  if target.exists():
   data=target.read_bytes()
   if len(data)!=item['size'] or zlib.crc32(data)!=item['crc32']:raise ValueError('existing file mismatch')
  else:
   r=Remote(archive['Url'],archive['Size'],budget);r.seek(item['offset']);header=r.read(30)
   fields=struct.unpack('<4s5H3L2H',header)
   if fields[0]!=b'PK\x03\x04' or fields[3]!=item['method']:raise ValueError('local header mismatch')
   name_len,extra_len=fields[-2:];local_name=r.read(name_len).decode('utf-8')
   if local_name!=item['name']:raise ValueError('local filename mismatch')
   r.seek(extra_len,1);remaining=item['compressed'];chunks=[]
   while remaining:
    chunk=r.read(min(remaining,4_000_000));chunks.append(chunk);remaining-=len(chunk)
   payload=b''.join(chunks)
   data=zlib.decompress(payload,-15) if item['method']==8 else payload if item['method']==0 else None
   if data is None or len(data)!=item['size'] or zlib.crc32(data)!=item['crc32']:raise ValueError('CRC or size mismatch')
   temp=target.with_suffix('.partial');temp.write_bytes(data);temp.replace(target)
  return dict(item,file='clips/'+target.name,sha256=hashlib.sha256(data).hexdigest())
 completed=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(download,item) for item in chosen]):
   completed.append(future.result())
   if len(completed)%20==0:print('VERIFIED',len(completed),flush=True)
 manifest['items']=sorted(completed,key=lambda x:x['name']);manifest['networkBytesReserved']=budget.bytes;manifest['count']=len(completed)
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print('DONE',len(completed),budget.bytes,flush=True)
if __name__=='__main__':main()
