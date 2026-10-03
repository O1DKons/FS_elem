import {isDeepStrictEqual} from 'node:util';
import {DatabaseSync} from 'node:sqlite';
import {existsSync,mkdirSync} from 'node:fs';
import {join,resolve,sep} from 'node:path';
import {validateDocument} from './validation.mjs';

export function initializeDatabase(path, {catalog,frames,annotations,expert,report}) {
  const db = new DatabaseSync(path);
  try {
    db.exec(`PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;
      CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE videos(id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, media_path TEXT NOT NULL UNIQUE, payload TEXT NOT NULL CHECK(json_valid(payload)));
      CREATE TABLE frame_times(video_id TEXT NOT NULL REFERENCES videos(id), frame_index INTEGER NOT NULL CHECK(frame_index>=0), seconds REAL NOT NULL CHECK(seconds>=0), PRIMARY KEY(video_id,frame_index));
      CREATE TABLE attempts(id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id), position INTEGER NOT NULL UNIQUE, start_frame INTEGER, end_frame INTEGER, start_seconds REAL, end_seconds REAL, attempt_group TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)));
      CREATE TABLE expert_labels(id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id), attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), provenance TEXT NOT NULL CHECK(json_valid(provenance)));
      CREATE TABLE revisions(revision INTEGER PRIMARY KEY, document TEXT NOT NULL CHECK(json_valid(document)));
      PRAGMA user_version=2;`);
    const videoInsert=db.prepare('INSERT INTO videos VALUES (?,?,?,?)');
    const frameInsert=db.prepare('INSERT INTO frame_times VALUES (?,?,?)');
    catalog.forEach((v,i)=>{
      videoInsert.run(v.id,i,`media/${v.id}.mp4`,JSON.stringify(v));
      frames[v.id].forEach((seconds,index)=>frameInsert.run(v.id,index,seconds));
    });
    const attemptInsert=db.prepare('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)');
    annotations.episodes.forEach((e,i)=>attemptInsert.run(e.id,e.videoId,i,e.startFrame??null,e.endFrame??null,e.start,e.end,e.attemptGroup,JSON.stringify(e)));
    const {labels,...provenance}=expert;
    const insertLabel=db.prepare('INSERT INTO expert_labels(video_id,attempt_id,payload,provenance) VALUES (?,NULL,?,?)');
    for(const label of labels) insertLabel.run(label.videoId,JSON.stringify(label),JSON.stringify(provenance));
    const insertMeta=db.prepare('INSERT INTO metadata VALUES (?,?)');
    insertMeta.run('document',JSON.stringify({...annotations,schemaVersion:2,episodes:undefined}));
    insertMeta.run('import',JSON.stringify(report));
    db.prepare('INSERT INTO revisions VALUES (?,?)').run(annotations.revision,JSON.stringify({...annotations,schemaVersion:2}));
    db.exec('COMMIT');
    if(db.prepare('PRAGMA integrity_check').get().integrity_check!=='ok') throw Error('Database integrity failed');
  } finally { db.close(); }
}
export function openStore(dataDir) {
  const path=join(dataDir,'fs-elem.sqlite');
  if(!existsSync(path)) {
    mkdirSync(dataDir,{recursive:true});
    initializeDatabase(path,{catalog:[],frames:{},annotations:{schemaVersion:2,revision:0,boundaryDefinition:'source presentation seconds',episodes:[]},expert:{labels:[],scope:'Empty local installation; no expert labels'},report:{mode:'empty_installation',createdAt:new Date().toISOString()}});
  }
  const db=new DatabaseSync(path);
  try {
    db.exec('PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;');
    if(db.prepare('PRAGMA user_version').get().user_version!==2) throw Error('Неподдерживаемая схема базы данных');
    const catalog=db.prepare('SELECT payload FROM videos ORDER BY position').all().map(v=>JSON.parse(v.payload));
    const frames=Object.fromEntries(catalog.map(v=>[v.id,db.prepare('SELECT seconds FROM frame_times WHERE video_id=? ORDER BY frame_index').all(v.id).map(r=>r.seconds)]));
    const read=()=>({...JSON.parse(db.prepare("SELECT value FROM metadata WHERE key='document'").get().value),episodes:db.prepare('SELECT payload FROM attempts ORDER BY position').all().map(e=>JSON.parse(e.payload))});
    return {
      read, catalog:()=>catalog, frames:id=>frames[id],
      importReport:()=>JSON.parse(db.prepare("SELECT value FROM metadata WHERE key='import'").get().value),
      media(id) {
        const row=db.prepare('SELECT media_path FROM videos WHERE id=?').get(id);
        if(!row) return undefined;
        const path=resolve(dataDir,row.media_path);
        if(!path.startsWith(resolve(dataDir)+sep)) throw Error('Invalid media path');
        return path;
      },
      save(body) {
        validateDocument(body,catalog,frames);
        db.exec('BEGIN IMMEDIATE');
        try {
          const prev=read();
          if(body.revision!==prev.revision) { const e=Error('Разметка изменена в другом окне. Обновите страницу.');e.status=409;throw e; }
          if(!body.capabilities?.includes('phase-events-v1')) {
            const oldById=new Map(prev.episodes.map(e=>[e.id,e]));
            const newById=new Map(body.episodes.map(e=>[e.id,e]));
            for(const id of new Set([...oldById.keys(),...newById.keys()])) {
              const old=oldById.get(id),next=newById.get(id);
              if(!isDeepStrictEqual(old?.events,next?.events) || !isDeepStrictEqual(old?.boundaryReview,next?.boundaryReview)) {
                const e=Error('Эта вкладка не поддерживает новые события. Скачайте свои правки и обновите страницу.');e.status=409;throw e;
              }
            }
          }
          const next={...prev,revision:prev.revision+1,updatedAt:new Date().toISOString(),episodes:body.episodes};
          if(!Number.isSafeInteger(next.revision)) throw Error('Revision overflow');
          // All labels imported in v2 are video-level; no automatic episode association.
          db.exec('DELETE FROM attempts');
          const insert=db.prepare('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)');
          next.episodes.forEach((e,i)=>insert.run(e.id,e.videoId,i,e.startFrame??null,e.endFrame??null,e.start,e.end,e.attemptGroup,JSON.stringify(e)));
          db.prepare("UPDATE metadata SET value=? WHERE key='document'").run(JSON.stringify({...next,episodes:undefined}));
          db.prepare('INSERT INTO revisions VALUES (?,?)').run(next.revision,JSON.stringify(next));
          db.exec('COMMIT'); return next;
        } catch(e) {db.exec('ROLLBACK');throw e;}
      },
      close:()=>db.close(),
    };
  } catch(e) {db.close();throw e;}
}
