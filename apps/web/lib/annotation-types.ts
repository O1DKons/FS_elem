export type Video={collection?:string;labelStatus?:string;id:string;title:string;duration:number;fps:number;width:number;height:number;filename:string;sha256:string};
export type EventName='lastContact'|'groupingStart'|'groupingComplete'|'opening'|'exitStable';
export type ReviewStatus='unreviewed'|'confirmed';
export type BoundaryReview={uncertaintyFrames:number;review:ReviewStatus};
export type EventMark=BoundaryReview & {frameIndex:number;time:number;source:'manual'};
export type Episode={id:string;videoId:string;start:number|null;end:number|null;startFrame?:number|null;endFrame?:number|null;note:string;attemptGroup:string;protocolElementSequence?:number;protocolComponentIndex?:number;protocolCode?:string;analysisProposal?:{call?:string;confidence:'low'|'medium'|'high';reason:string;source:'visual_review'|'unreviewed';windowStart?:number;windowEnd?:number};events?:Partial<Record<EventName,EventMark>>;boundaryReview?:{start?:BoundaryReview;end?:BoundaryReview}};
export type Saved={revision:number;episodes:Episode[];error?:string};
