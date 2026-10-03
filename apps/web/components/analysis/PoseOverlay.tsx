'use client';
import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { AnalysisPose } from '../../lib/analysis-types';
import {
  contentRect,
  drawablePose,
  nearestPoseFrame,
} from '../../lib/pose-overlay.mjs';

export default function PoseOverlay({
  videoRef,
  pose,
  enabled,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  pose: AnalysisPose | null;
  enabled: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const video = videoRef.current,
      canvas = canvasRef.current;
    if (!video || !canvas) return;
    let frameId = 0,
      presentedFrameId = 0,
      active = true,
      lastVisible = false,
      displayTime = video.currentTime;
    const usePresentedFrames =
      typeof video.requestVideoFrameCallback === 'function';
    const presented: VideoFrameRequestCallback = (_now, metadata) => {
      if (!active) return;
      displayTime = metadata.mediaTime;
      presentedFrameId = video.requestVideoFrameCallback(presented);
    };
    if (usePresentedFrames)
      presentedFrameId = video.requestVideoFrameCallback(presented);
    const seeked = () => {
      displayTime = video.currentTime;
    };
    video.addEventListener('seeked', seeked);
    const draw = () => {
      const width = video.clientWidth,
        height = video.clientHeight,
        dpr = window.devicePixelRatio || 1;
      if (
        canvas.width !== Math.round(width * dpr) ||
        canvas.height !== Math.round(height * dpr)
      ) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      let hasPoints = false;
      if (enabled && pose && video.readyState >= 2 && !video.seeking) {
        const rotated =
          pose.geometry.rotation === 90 || pose.geometry.rotation === 270;
        const displayWidth = rotated
          ? pose.geometry.height
          : pose.geometry.width;
        const displayHeight = rotated
          ? pose.geometry.width
          : pose.geometry.height;
        // Refuse a mismatched geometry instead of drawing a distorted skeleton.
        const geometryMatches =
          video.videoWidth === displayWidth &&
          video.videoHeight === displayHeight;
        const rect = geometryMatches
          ? contentRect(width, height, displayWidth, displayHeight)
          : null;
        const sourceTime = usePresentedFrames ? displayTime : video.currentTime;
        const frame = nearestPoseFrame(
          pose.frames,
          sourceTime,
          pose.maxTimeDelta,
        );
        if (
          frame &&
          rect &&
          Math.abs(frame.time - sourceTime) <= frame.tolerance + 1e-9
        ) {
          const drawable = drawablePose(
            frame,
            pose.links,
            pose.geometry,
            rect,
            pose.minConfidence,
          );
          ctx.lineWidth = 2.5;
          ctx.strokeStyle = '#6de6fb';
          ctx.shadowColor = '#123552';
          ctx.shadowBlur = 3;
          for (const [a, b] of drawable.links) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
          ctx.shadowBlur = 0;
          for (const point of drawable.points) {
            ctx.beginPath();
            ctx.arc(point.x, point.y, 3.5, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.fill();
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = '#1687a3';
            ctx.stroke();
          }
          hasPoints = drawable.points.length > 0;
        }
      }
      if (lastVisible !== hasPoints) {
        lastVisible = hasPoints;
        setVisible(hasPoints);
      }
    };
    const tick = () => {
      if (!active) return;
      draw();
      frameId = requestAnimationFrame(tick);
    };
    const observer = new ResizeObserver(draw);
    observer.observe(video);
    tick();
    return () => {
      active = false;
      cancelAnimationFrame(frameId);
      if (usePresentedFrames) video.cancelVideoFrameCallback(presentedFrameId);
      video.removeEventListener('seeked', seeked);
      observer.disconnect();
    };
  }, [videoRef, pose, enabled]);
  return (
    <>
      <canvas
        ref={canvasRef}
        className="analysis-pose-canvas"
        aria-hidden="true"
      />
      {enabled && pose && !visible && (
        <span className="analysis-pose-gap">
          В этом кадре нет доступных точек позы
        </span>
      )}
    </>
  );
}
