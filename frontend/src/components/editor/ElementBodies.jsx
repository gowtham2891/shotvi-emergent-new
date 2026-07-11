import React, { useMemo } from "react";
import { useAppStore } from "@/store/useAppStore";
import { getCaptionStylePreview } from "@/data/captionStylePreview";
import { buildCaptionLines, findActiveLine, findActiveWordIndex } from "@/lib/captionLines";

/**
 * Per-type element content renderers — extracted from ElementRenderer so
 * both the interactive editor canvas (drag/select/TransformBox) and any
 * read-only preview (currently: the Export page's live draft preview) can
 * render identical element content without duplicating caption/overlay
 * logic. Pure content only — no drag handlers, no positioning wrapper.
 */
export const ElementBody = ({ element, canvasH }) => {
  switch (element.type) {
    case "caption":
      return <CaptionBody element={element} canvasH={canvasH} />;
    case "headline":
      return <HeadlineBody element={element} canvasH={canvasH} />;
    case "progress":
      return <ProgressBody element={element} canvasH={canvasH} />;
    case "logo":
      return <LogoBody element={element} canvasH={canvasH} />;
    case "sticker":
      return <StickerBody element={element} canvasH={canvasH} />;
    default:
      return null;
  }
};

const animationClass = (anim) => {
  switch (anim) {
    case "pop":
      return "anim-pop";
    case "fade":
      return "anim-fade";
    case "bounce":
      return "anim-bounce";
    default:
      return "";
  }
};

const CaptionBody = ({ element, canvasH }) => {
  const transcript = useAppStore((s) => s.transcript);
  const currentTime = useAppStore((s) => s.currentTime);

  const { presetId, font, fontSize, animation, pill } = element.props;
  const preview = getCaptionStylePreview(presetId);
  const isKaraoke = animation === "karaoke";

  // Mirrors services/caption_renderer.py's group_words_into_lines: chunk
  // into wordsPerLine-word lines (4, or 2 for big-bold), each held on
  // screen for [lineStart, lineEnd) — not a fast sliding word-window — so
  // preview line breaks and pacing match export.
  const lines = useMemo(
    () => buildCaptionLines(transcript, preview.wordsPerLine),
    [transcript, preview.wordsPerLine]
  );
  const activeLine = findActiveLine(lines, currentTime);
  const activeWordIdx = findActiveWordIndex(activeLine, currentTime);

  // User's manual pill toggle overrides the preset's own box (an explicit
  // customization); otherwise fall back to the backend style's real
  // back_color/border_style-derived box, so the untouched default already
  // matches what caption_renderer.py burns in.
  const pillStyle = pill?.enabled
    ? {
        background: hexToRgba(pill.color, pill.opacity),
        padding: `${pill.padding}px ${pill.padding * 1.6}px`,
        borderRadius: `${pill.radius}px`,
      }
    : preview.box || {};

  // No line is on screen at this instant (a real gap between lines, just
  // like the backend's ASS timeline) — show nothing, matching export.
  if (!activeLine) return null;

  return (
    <div
      className="flex flex-wrap justify-center gap-x-2 gap-y-1 max-w-[70vw] text-center"
      style={{ ...pillStyle, width: "max-content", maxWidth: 380 }}
    >
      {activeLine.words.map((w, gIdx) => {
        // Karaoke 3-state progression, mirroring the backend's
        // color_unspoken -> color_highlight -> color_spoken transition.
        // Non-karaoke animations show every word in its base (unspoken)
        // color; animationClass() drives the motion instead.
        const role = !isKaraoke ? "unspoken" : gIdx < activeWordIdx ? "spoken" : gIdx === activeWordIdx ? "active" : "unspoken";
        const color =
          role === "active" ? preview.colorHighlight : role === "spoken" ? preview.colorSpoken : preview.colorUnspoken;
        return (
          <span
            key={`${gIdx}-${w.text}`}
            className={gIdx === activeWordIdx ? animationClass(animation) : ""}
            style={{
              fontFamily: preview.fontFamily,
              fontWeight: preview.fontWeight,
              color,
              textShadow: preview.textShadow,
              fontSize: fontSize * canvasH,
              lineHeight: 1.25,
              transform: role === "active" && isKaraoke ? "scale(1.06)" : "scale(1)",
              transition: "color 120ms linear, transform 120ms linear",
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};

const HeadlineBody = ({ element, canvasH }) => {
  const p = element.props;
  return (
    <div
      style={{
        fontFamily: p.font,
        fontSize: p.fontSize * canvasH,
        color: p.color,
        fontWeight: p.weight,
        fontStyle: p.italic ? "italic" : "normal",
        textTransform: p.uppercase ? "uppercase" : "none",
        WebkitTextStroke: p.stroke ? "1.5px rgba(0,0,0,0.85)" : "none",
        textShadow: "0 4px 18px rgba(0,0,0,0.55)",
        whiteSpace: "nowrap",
        letterSpacing: "0.02em",
      }}
    >
      {p.text}
    </div>
  );
};

const ProgressBody = ({ element, canvasH }) => {
  const currentTime = useAppStore((s) => s.currentTime);
  const duration = useAppStore((s) => s.duration);
  const p = element.props;
  const canvasW = (canvasH * 9) / 16;
  const pct = duration ? (currentTime / duration) * 100 : 0;
  return (
    <div
      style={{
        width: p.width * canvasW,
        height: Math.max(3, p.height * canvasH),
        background: "rgba(255,255,255,0.18)",
        borderRadius: 999,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: p.color,
          borderRadius: 999,
          boxShadow: `0 0 8px ${p.color}`,
        }}
      />
    </div>
  );
};

const LogoBody = ({ element, canvasH }) => {
  const p = element.props;
  return (
    <div
      className="flex items-center gap-1.5"
      style={{ fontFamily: p.font, fontSize: p.fontSize * canvasH }}
    >
      <div
        className="rounded-full bg-gradient-to-br from-[#7c3aed] to-[#a78bfa] flex items-center justify-center text-white font-bold"
        style={{
          width: p.fontSize * canvasH * 1.8,
          height: p.fontSize * canvasH * 1.8,
          fontSize: p.fontSize * canvasH * 0.9,
        }}
      >
        {p.avatar}
      </div>
      <span className="text-white/90 font-semibold drop-shadow-[0_2px_6px_rgba(0,0,0,0.6)]">
        {p.text}
      </span>
    </div>
  );
};

const StickerBody = ({ element, canvasH }) => (
  <div
    style={{
      fontSize: element.props.fontSize * canvasH,
      filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.45))",
      lineHeight: 1,
    }}
  >
    {element.props.emoji}
  </div>
);

function hexToRgba(hex, alpha = 1) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

export default ElementBody;
