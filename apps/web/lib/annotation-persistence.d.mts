import type {Episode} from './annotation-types';
export type PersistenceState={saving:boolean;failed:boolean;error:unknown;revision:number};
export function createAnnotationPersistence(options:{revision:number;save:(revision:number,episodes:Episode[])=>Promise<{revision:number}>;onState?:(state:PersistenceState)=>void;onSaved?:(episodes:Episode[],revision:number)=>void}):{readonly revision:number;readonly failed:boolean;enqueue(snapshot:Episode[]):void;retry(snapshot:Episode[]):void;idle():Promise<void>};
