/** @param {any} e @param {string} key @param {number} index @param {number[]} times */
export function markEvent(e,key,index,times) {
 if(!Number.isSafeInteger(index)||!Number.isFinite(times[index]))throw new Error('Кадр недоступен');
 return {...e,events:{...e.events,[key]:{frameIndex:index,time:times[index],uncertaintyFrames:e.events?.[key]?.uncertaintyFrames??0,source:'manual',review:'unreviewed'}}};
}
/** @param {any} e @param {'start'|'end'} key @param {number} index @param {number[]} times */
export function markBoundary(e,key,index,times) {
 if(!Number.isSafeInteger(index)||!Number.isFinite(times[index]))throw new Error('Кадр недоступен');
 return {...e,[key]:times[index],[key+'Frame']:index,boundaryReview:{...e.boundaryReview,[key]:{uncertaintyFrames:e.boundaryReview?.[key]?.uncertaintyFrames??0,review:'unreviewed'}}};
}
