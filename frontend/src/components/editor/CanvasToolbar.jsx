import React, { useState } from "react";
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  Frame,
  Plus,
  Type,
  MessageSquare,
  BarChart3,
  Sticker,
  Image as ImageIcon,
  Check,
} from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { EDITOR } from "@/constants/testIds";

const SAFE_ZONES = [
  { key: "off", label: "Off" },
  { key: "instagram", label: "Instagram" },
  { key: "youtube", label: "YouTube" },
];

const ADD_TYPES = [
  { type: "headline", label: "Hook headline", icon: Type },
  { type: "sticker", label: "Emoji sticker", icon: Sticker },
  { type: "progress", label: "Progress bar", icon: BarChart3 },
  { type: "logo", label: "Logo / handle", icon: ImageIcon },
];

/**
 * CanvasToolbar — compact vertical rail on the left of the canvas area.
 * Zoom controls, safe-zone selector, add element menu, fit-to-viewport.
 * Dropdowns open to the right so they don't spill off the left edge.
 */
export const CanvasToolbar = () => {
  const canvasZoom = useAppStore((s) => s.canvasZoom);
  const zoomIn = useAppStore((s) => s.zoomIn);
  const zoomOut = useAppStore((s) => s.zoomOut);
  const fitScreen = useAppStore((s) => s.fitScreen);
  const safeZoneMode = useAppStore((s) => s.safeZoneMode);
  const setSafeZoneMode = useAppStore((s) => s.setSafeZoneMode);
  const addElement = useAppStore((s) => s.addElement);
  const elements = useAppStore((s) => s.elements);
  const toggleElementVisibility = useAppStore(
    (s) => s.toggleElementVisibility
  );
  const setSelected = useAppStore((s) => s.setSelected);

  const [safeOpen, setSafeOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const addOrShow = (type) => {
    // If an element of that type exists but hidden — show it. Otherwise add new.
    const existing = elements.find((el) => el.type === type);
    if (existing && !existing.visible) {
      toggleElementVisibility(existing.id);
      setSelected(existing.id);
    } else {
      addElement(type);
    }
    setAddOpen(false);
  };

  return (
    <div className="w-12 shrink-0 flex flex-col items-center gap-1.5 bg-[#0b0b10]/85 backdrop-blur-xl border-r border-[#2a2a35] py-2.5 z-[90]">
      {/* Add element */}
      <div className="relative">
        <button
          data-testid={EDITOR.addElementMenu}
          onClick={() => setAddOpen((v) => !v)}
          title="Add element"
          className="w-8 h-8 flex items-center justify-center rounded-md text-white bg-[#7c3aed] hover:bg-[#6d28d9] transition-colors"
        >
          <Plus size={14} />
        </button>
        {addOpen && (
          <div className="absolute top-0 left-full ml-1.5 w-52 bg-[#111116] border border-[#2a2a35] rounded-lg shadow-2xl overflow-hidden py-1 z-[95]">
            {ADD_TYPES.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.type}
                  data-testid={EDITOR.addElementOption(t.type)}
                  onClick={() => addOrShow(t.type)}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[#d4d4d8] hover:bg-[#7c3aed]/15 hover:text-white transition-colors"
                >
                  <Icon size={13} className="text-[#c4b5fd]" />
                  {t.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="w-6 h-px bg-[#2a2a35] my-0.5" />

      {/* Zoom controls */}
      <button
        data-testid={EDITOR.zoomIn}
        onClick={zoomIn}
        title="Zoom in"
        className="w-8 h-8 flex items-center justify-center rounded-md text-[#a1a1aa] hover:text-white hover:bg-white/5 transition-colors"
      >
        <ZoomIn size={14} />
      </button>
      <div
        data-testid={EDITOR.zoomLevel}
        className="text-[10px] font-mono text-white leading-none py-0.5"
      >
        {Math.round(canvasZoom * 100)}%
      </div>
      <button
        data-testid={EDITOR.zoomOut}
        onClick={zoomOut}
        title="Zoom out"
        className="w-8 h-8 flex items-center justify-center rounded-md text-[#a1a1aa] hover:text-white hover:bg-white/5 transition-colors"
      >
        <ZoomOut size={14} />
      </button>
      <button
        data-testid={EDITOR.zoomFit}
        onClick={fitScreen}
        title="Fit to viewport"
        className="w-8 h-8 flex items-center justify-center rounded-md text-[#a1a1aa] hover:text-white hover:bg-white/5 transition-colors"
      >
        <Maximize2 size={14} />
      </button>

      <div className="w-6 h-px bg-[#2a2a35] my-0.5" />

      {/* Safe zone */}
      <div className="relative">
        <button
          data-testid={EDITOR.safeZoneToggle}
          onClick={() => setSafeOpen((v) => !v)}
          title={`Safe zone: ${SAFE_ZONES.find((s) => s.key === safeZoneMode)?.label}`}
          className={`w-8 h-8 flex items-center justify-center rounded-md transition-colors border ${
            safeZoneMode !== "off"
              ? "bg-[#7c3aed]/15 border-[#7c3aed]/40 text-white"
              : "border-transparent text-[#a1a1aa] hover:text-white hover:bg-white/5"
          }`}
        >
          <Frame size={14} />
        </button>
        {safeOpen && (
          <div className="absolute bottom-0 left-full ml-1.5 w-40 bg-[#111116] border border-[#2a2a35] rounded-lg shadow-2xl overflow-hidden py-1 z-[95]">
            {SAFE_ZONES.map((s) => (
              <button
                key={s.key}
                data-testid={EDITOR.safeZoneOption(s.key)}
                onClick={() => {
                  setSafeZoneMode(s.key);
                  setSafeOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2 text-xs transition-colors ${
                  safeZoneMode === s.key
                    ? "bg-[#7c3aed]/15 text-white"
                    : "text-[#d4d4d8] hover:bg-white/5 hover:text-white"
                }`}
              >
                {s.label}
                {safeZoneMode === s.key && (
                  <Check size={12} className="text-[#c4b5fd]" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default CanvasToolbar;
