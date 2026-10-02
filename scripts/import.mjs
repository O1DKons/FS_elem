import {importLegacy} from '../server/importer.mjs';
import {loadConfig} from './config.mjs';
const args=process.argv.slice(2);
const source=args.find(a=>!a.startsWith('--'));
if(!source || args.some(a=>a.startsWith('--') && a!=='--dry-run')) {
  console.error('Usage: node scripts/import.mjs /path/to/legacy/outputs [--dry-run]');process.exitCode=1;
} else {
  try {const report=await importLegacy(source,loadConfig().dataDir,{dryRun:args.includes('--dry-run')});console.log(JSON.stringify({...report,sourceFiles:undefined},null,2));}
  catch(e) {console.error(e.message);process.exitCode=1;}
}
