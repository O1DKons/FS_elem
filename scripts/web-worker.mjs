import {join} from 'node:path';
import {loadConfig,projectRoot} from './config.mjs';
import {openStore} from '../server/store.mjs';
import {createApi} from '../server/api.mjs';
import {createServer} from '../apps/web/node_modules/vite/dist/node/index.js';
const config=loadConfig(projectRoot,process.argv[2]);
const store=openStore(config.dataDir);
let web;
try {
  web=await createServer({root:join(projectRoot,'apps/web'),configFile:join(projectRoot,'apps/web/vite.config.ts'),server:{host:config.host,port:config.port,strictPort:true},plugins:[{name:'fs-elem-api',enforce:'pre',configureServer(server){server.middlewares.use(createApi(store,config));}}]});
  await web.listen();process.send?.({ready:true});
  process.once('disconnect',async()=>{await web.close();store.close();process.exit(0)});
} catch(e) {console.error(e.message);await web?.close();store.close();process.exit(1);}
