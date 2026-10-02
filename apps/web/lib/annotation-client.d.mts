import type {Video,Saved,Episode} from './annotation-types';
export class AnnotationHttpError extends Error {status:number;constructor(message:string,status:number)}
export function createAnnotationClient(fetcher?:typeof fetch):{catalog():Promise<Video[]>;frames(id:string):Promise<number[]>;annotations():Promise<Saved>;save(revision:number,episodes:Episode[]):Promise<Saved>};
