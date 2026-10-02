/** @param {EventTarget & {readyState:number}} video @param {(ready:boolean)=>void} onReady */
export function observeVideoReadiness(video,onReady) {
  const update=()=>onReady(video.readyState>=1);
  video.addEventListener('loadedmetadata',update);
  update(); // The browser may finish preload before React hydrates the video.
  return ()=>video.removeEventListener('loadedmetadata',update);
}
