import {spawnSync} from 'node:child_process';
import {join} from 'node:path';
import {projectRoot} from './config.mjs';
const result=spawnSync(process.execPath,[join(projectRoot,'apps/web/node_modules/vinext/dist/cli.js'),'build'],{cwd:join(projectRoot,'apps/web'),stdio:'inherit'});
if(result.error)console.error(result.error.message);
process.exitCode=result.status??1;
