import React, { useRef, useEffect, useCallback } from "react";
import { useAppStore, clamp } from "@/store/useAppStore";
import { CanvasToolbar } from "@/components/editor/CanvasToolbar";
import { SafeZoneOverlay } from "@/components/editor/SafeZoneOverlay";
import { SmartGuides } from "@/components/editor/SmartGuides";
import { ElementRenderer } from "@/components/editor/ElementRenderer";
import { EDITOR } from "@/constants/testIds";

const NUDGE = 1; // px
const NUDGE_BIG = 10; // px with shift

const STAGE_WIDTH = 360;
const STAGE_HEIGHT = 640;
const FIT_PADDING_PX = 32; // breathing room on each side at 100%-fit zoom

// Largest zoom that keeps the full 9:16 stage inside the viewport, padded.
const computeFitZoom = (viewportEl) => {
  if (!viewportEl) return 1;
  const { width, height } = viewportEl.getBoundingClientRect();
  const availW = Math.max(width - FIT_PADDING_PX * 2, 40);
  const availH = Math.max(height - FIT_PADDING_PX * 2, 40);
  return clamp(Math.min(availW / STAGE_WIDTH, availH / STAGE_HEIGHT), 0.4, 3);
};

/**
 * CanvasArea — the center panel: toolbar + zoomable/pannable 9:16 stage.
 * - ctrl/cmd + scroll to zoom, space+drag (or middle mouse) to pan
 * - arrows nudge selected element (shift = 10px), Delete removes
 *   non-caption elements, Escape clears selection
 * - click empty stage → clear selection
 */
export const CanvasArea = ({ currentClip }) => {
  const stageRef = useRef(null);
  const viewportRef = useRef(null);
  const spaceHeld = useRef(false);
  const videoRef = useRef(null);

  const elements = useAppStore((s) => s.elements);
  const selectedElementId = useAppStore((s) => s.selectedElementId);
  const clearSelection = useAppStore((s) => s.clearSelection);
  const removeElement = useAppStore((s) => s.removeElement);
  const updateElement = useAppStore((s) => s.updateElement);
  const zoom = useAppStore((s) => s.canvasZoom);
  const setCanvasZoom = useAppStore((s) => s.setCanvasZoom);
  const pan = useAppStore((s) => s.canvasPan);
  const setCanvasPan = useAppStore((s) => s.setCanvasPan);
  const currentTime = useAppStore((s) => s.currentTime);
  const isPlaying = useAppStore((s) => s.isPlaying);
  const fitRequestId = useAppStore((s) => s.fitRequestId);
  const videoUrl = currentClip?.videoUrl || currentClip?.previewUrl || null;

  // ---------- Real video sync ----------
  // The <video> drives store.currentTime while playing; store.isPlaying
  // drives play/pause; external seeks (timeline clicks) push back into the
  // video when they diverge by more than 300ms.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isPlaying) {
      v.play().catch(() => useAppStore.getState().setPlaying(false));
    } else {
      v.pause();
    }
  }, [isPlaying, videoUrl]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (Math.abs(v.currentTime - currentTime) > 0.3) {
      v.currentTime = currentTime;
    }
  }, [currentTime]);

  // ---------- Keyboard ----------
  const onKeyDown = useCallback(
    (e) => {
      // Don't hijack typing in inputs
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.code === "Space") {
        spaceHeld.current = true;
        e.preventDefault();
        return;
      }
      if (e.key === "Escape") {
        clearSelection();
        return;
      }

      const s = useAppStore.getState();
      const sel = s.elements.find((el) => el.id === s.selectedElementId);
      if (!sel) return;

      if (e.key === "Delete" || e.key === "Backspace") {
        if (sel.type !== "caption") removeElement(sel.id);
        return;
      }

      const rect = stageRef.current?.getBoundingClientRect();
      if (!rect) return;
      const step = e.shiftKey ? NUDGE_BIG : NUDGE;
      const dx = step / rect.width;
      const dy = step / rect.height;

      let moved = false;
      let { x, y } = sel;
      if (e.key === "ArrowLeft") { x = clamp(x - dx, 0.02, 0.98); moved = true; }
      if (e.key === "ArrowRight") { x = clamp(x + dx, 0.02, 0.98); moved = true; }
      if (e.key === "ArrowUp") { y = clamp(y - dy, 0.02, 0.98); moved = true; }
      if (e.key === "ArrowDown") { y = clamp(y + dy, 0.02, 0.98); moved = true; }
      if (moved) {
        e.preventDefault();
        updateElement(sel.id, { x, y });
      }
    },
    [clearSelection, removeElement, updateElement]
  );

  const onKeyUp = useCallback((e) => {
    if (e.code === "Space") spaceHeld.current = false;
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [onKeyDown, onKeyUp]);

  // ---------- Fit-to-viewport zoom ----------
  // Default/initial state (not a one-time constant): recomputed on clip
  // load, on "Fit" clicks (fitRequestId, bumped from the toolbar), and on
  // window resize, since the right zoom depends on the actual viewport
  // size, not a fixed percentage. Manual +/- zoom keeps working between
  // these events.
  const applyFit = useCallback(() => {
    const z = computeFitZoom(viewportRef.current);
    setCanvasZoom(z);
    setCanvasPan({ x: 0, y: 0 });
  }, [setCanvasZoom, setCanvasPan]);

  useEffect(() => {
    applyFit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentClip?.id, fitRequestId]);

  useEffect(() => {
    let raf = null;
    const onResize = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(applyFit);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [applyFit]);

  // ---------- Zoom (ctrl/cmd + wheel) ----------
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const onWheel = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const s = useAppStore.getState();
      s.setCanvasZoom(s.canvasZoom - Math.sign(e.deltaY) * 0.08);
    };
    vp.addEventListener("wheel", onWheel, { passive: false });
    return () => vp.removeEventListener("wheel", onWheel);
  }, []);

  // ---------- Pan (space+drag or middle mouse) ----------
  const onViewportPointerDown = (e) => {
    const isPanGesture = spaceHeld.current || e.button === 1;
    if (!isPanGesture) return;
    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const startPan = useAppStore.getState().canvasPan;
    const move = (ev) => {
      setCanvasPan({
        x: startPan.x + (ev.clientX - startX),
        y: startPan.y + (ev.clientY - startY),
      });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="flex-1 flex min-h-0 relative">
      <CanvasToolbar />

      <div
        ref={viewportRef}
        data-testid={EDITOR.canvas}
        onPointerDown={onViewportPointerDown}
        onClick={() => clearSelection()}
        className="flex-1 min-h-0 flex items-center justify-center overflow-hidden relative"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 40%, rgba(124,58,237,0.07), transparent 70%), #060608",
        }}
      >
        {/* Zoom/pan wrapper */}
        <div
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transition: "transform 60ms linear",
          }}
        >
          {/* 9:16 stage */}
          <div
            ref={stageRef}
            data-testid={EDITOR.canvasStage}
            onClick={(e) => e.stopPropagation()}
            className="relative rounded-xl overflow-hidden shadow-[0_24px_80px_rgba(0,0,0,0.65),0_0_0_1px_rgba(124,58,237,0.22)]"
            style={{ width: STAGE_WIDTH, height: STAGE_HEIGHT }}
          >
            {videoUrl ? (
              /* Real clip video (auto-cropped vertical from the pipeline) */
              <video
                ref={videoRef}
                src={videoUrl}
                className="absolute inset-0 w-full h-full object-contain bg-black"
                playsInline
                preload="auto"
                onTimeUpdate={(e) => {
                  const s = useAppStore.getState();
                  if (s.isPlaying) s.seek(e.currentTarget.currentTime);
                }}
                onEnded={() => {
                  const s = useAppStore.getState();
                  s.setPlaying(false);
                  s.seek(0);
                }}
                onError={() => {
                  // Non-fatal: keep the editor usable without the preview
                  console.warn("Clip video failed to load:", videoUrl);
                }}
              />
            ) : (
              <>
                {/* Mock video frame (no real clip loaded) */}
                <div
                  className="absolute inset-0"
                  style={{
                    background:
                      "linear-gradient(160deg, #17102b 0%, #0d0a18 45%, #1a0f2e 100%)",
                  }}
                />
                <div className="absolute inset-0 opacity-40"
                  style={{
                    background:
                      "radial-gradient(circle at 30% 30%, rgba(167,139,250,0.25), transparent 55%), radial-gradient(circle at 72% 68%, rgba(124,58,237,0.2), transparent 50%)",
                  }}
                />
                {/* Speaker silhouette placeholder */}
                <div className="absolute left-1/2 top-[38%] -translate-x-1/2 -translate-y-1/2 w-40 h-40 rounded-full bg-gradient-to-b from-[#2a1d4d] to-[#160f2b] border border-white/5 flex items-center justify-center">
                  <span className="text-5xl">🎙️</span>
                </div>
              </>
            )}
            {/* Virality badge */}
            {currentClip && (
              <div className="absolute top-3 right-3 z-30 px-2 py-1 rounded-md bg-black/55 backdrop-blur border border-[#22ff9c]/30 text-[#22ff9c] text-[11px] font-mono font-bold pointer-events-none">
                {currentClip.virality ?? currentClip.score ?? "—"} · VIRAL
              </div>
            )}
            {/* Timecode */}
            <div className="absolute bottom-2 left-3 z-30 text-[10px] font-mono text-white/45 pointer-events-none">
              {currentTime.toFixed(1)}s
            </div>

            {/* Elements */}
            {elements.map((el) => (
              <ElementRenderer key={el.id} element={el} canvasRef={stageRef} />
            ))}

            {/* Overlays */}
            <SmartGuides />
            <SafeZoneOverlay />
          </div>
        </div>

        {/* Selection hint */}
        {!selectedElementId && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 text-[11px] text-[#5a5a66] pointer-events-none">
            Click an element to select · drag to move · ⌘/Ctrl+scroll to zoom · Space+drag to pan
          </div>
        )}
      </div>
    </div>
  );
};

export default CanvasArea;
