export function layout(crop){const scale=Math.min(640/crop[2],640/crop[3]);return {scale,x:(640-crop[2]*scale)/2,y:(640-crop[3]*scale)/2};}
export function project(point,crop){const t=layout(crop);return {x:(point.x*1280-crop[0])*t.scale+t.x,y:(point.y*720-crop[1])*t.scale+t.y};}
