import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Type,
  Music2,
  Download,
  Eye,
  EyeOff,
  ChevronUp,
  ChevronDown,
  Trash2,
  Sparkles,
  MessageSquare,
  BarChart3,
  AtSign,
  Play,
} from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { MUSIC_LIBRARY } from "@/data/mockData";
// Caption presets mirror the backend's caption style ids (STYLES in
// services/caption_renderer.py) so exports always burn the selected style.
// CAPTION_FONTS are the three bundled Telugu caption fonts the backend
// resolves deterministically via fontsdir (services/fonts.py :: CAPTION_FONTS).
import { CAPTION_STYLES, CAPTION_FONTS } from "@/api/renders";
import { getCaptionFontStack } from "@/data/captionStylePreview";
import { getCaptionStylePreview } from "@/data/captionStylePreview";
import { EDITOR } from "@/constants/testIds";

const TABS = [
  { key: "style", label: "Style", icon: Type, testId: EDITOR.tabStyle },
  { key: "music", label: "Music", icon: Music2, testId: EDITOR.tabMusic },
  { key: "export", label: "Export", icon: Download, testId: EDITOR.tabExport },
];

const TYPE_ICONS = {
  caption: Type,
  headline: MessageSquare,
  progress: BarChart3,
  logo: AtSign,
};

const ANIMATIONS = [
  { id: "none", label: "None" },
  { id: "pop", label: "Pop" },
  { id: "fade", label: "Fade" },
  { id: "bounce", label: "Bounce" },
  { id: "karaoke", label: "Karaoke" },
];

const POSITION_PRESETS = [
  { id: "top", label: "Top" },
  { id: "center", label: "Center" },
  { id: "lower-third", label: "Lower ⅓" },
  { id: "bottom-safe", label: "Bottom Safe" },
];

/**
 * Inspector — right panel. Style / Music / Export tabs.
 */
export const Inspector = () => {
  const [tab, setTab] = useState("style");

  return (
    <aside className="border-l border-[#1c1c24] bg-[#0a0a0f] flex flex-col overflow-hidden">
      {/* Tabs */}
      <div className="flex border-b border-[#1c1c24]">
        {TABS.map(({ key, label, icon: Icon, testId }) => (
          <button
            key={key}
            data-testid={testId}
            onClick={() => setTab(key)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-3 text-xs font-semibold transition-colors ${
              tab === key
                ? "text-[#c4b5fd] bg-[#7c3aed]/10 border-b-2 border-[#7c3aed]"
                : "text-[#5a5a66] hover:text-[#9a9aa6]"
            }`}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {tab === "style" && <StyleTab />}
        {tab === "music" && <MusicTab />}
        {tab === "export" && <ExportTab />}
      </div>
    </aside>
  );
};

/* ============================ STYLE ============================ */

const StyleTab = () => {
  const elements = useAppStore((s) => s.elements);
  const selectedId = useAppStore((s) => s.selectedElementId);
  const selected = elements.find((el) => el.id === selectedId);

  return (
    <>
      <ElementList />
      <PositionSection />
      {selected?.type === "caption" && <CaptionSection element={selected} />}
      {selected?.type === "headline" && <HeadlineSection element={selected} />}
      {!selected && (
        <p className="text-[11px] text-[#5a5a66] leading-relaxed">
          Select an element on the canvas — or toggle one on above — to edit
          its style.
        </p>
      )}
    </>
  );
};

const SectionTitle = ({ children }) => (
  <p className="text-[10px] uppercase tracking-[0.22em] text-[#5a5a66] mb-2">
    {children}
  </p>
);

const ElementList = () => {
  const elements = useAppStore((s) => s.elements);
  const selectedId = useAppStore((s) => s.selectedElementId);
  const setSelected = useAppStore((s) => s.setSelected);
  const toggleVisibility = useAppStore((s) => s.toggleElementVisibility);
  const bringForward = useAppStore((s) => s.bringForward);
  const sendBackward = useAppStore((s) => s.sendBackward);
  const removeElement = useAppStore((s) => s.removeElement);

  return (
    <div>
      <SectionTitle>Elements</SectionTitle>
      <div className="space-y-1">
        {[...elements].reverse().map((el) => {
          const Icon = TYPE_ICONS[el.type] || Sparkles;
          const isSel = el.id === selectedId;
          return (
            <div
              key={el.id}
              onClick={() => setSelected(el.id)}
              className={`group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer border transition-colors ${
                isSel
                  ? "bg-[#7c3aed]/12 border-[#7c3aed]/40"
                  : "border-transparent hover:bg-white/[0.03]"
              }`}
            >
              <Icon size={12} className={isSel ? "text-[#c4b5fd]" : "text-[#5a5a66]"} />
              <span className={`flex-1 text-[11px] capitalize ${el.visible ? "text-[#d7d7de]" : "text-[#4a4a55] line-through"}`}>
                {el.type}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); sendBackward(el.id); }}
                className="opacity-0 group-hover:opacity-100 text-[#5a5a66] hover:text-white transition-opacity"
                title="Send backward"
              >
                <ChevronDown size={12} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); bringForward(el.id); }}
                className="opacity-0 group-hover:opacity-100 text-[#5a5a66] hover:text-white transition-opacity"
                title="Bring forward"
              >
                <ChevronUp size={12} />
              </button>
              {el.type !== "caption" && (
                <button
                  onClick={(e) => { e.stopPropagation(); removeElement(el.id); }}
                  className="opacity-0 group-hover:opacity-100 text-[#5a5a66] hover:text-red-400 transition-opacity"
                  title="Delete"
                >
                  <Trash2 size={12} />
                </button>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); toggleVisibility(el.id); }}
                className="text-[#5a5a66] hover:text-white"
                title={el.visible ? "Hide" : "Show"}
              >
                {el.visible ? <Eye size={13} /> : <EyeOff size={13} />}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const PositionSection = () => {
  const applyPositionPreset = useAppStore((s) => s.applyPositionPreset);
  const selectedId = useAppStore((s) => s.selectedElementId);
  return (
    <div>
      <SectionTitle>Position</SectionTitle>
      <div className="grid grid-cols-2 gap-1.5">
        {POSITION_PRESETS.map((p) => (
          <button
            key={p.id}
            data-testid={EDITOR.positionPresetBtn(p.id)}
            disabled={!selectedId}
            onClick={() => applyPositionPreset(p.id)}
            className="px-2 py-1.5 rounded-md text-[11px] font-medium bg-[#131318] border border-[#22222c] text-[#9a9aa6] hover:border-[#7c3aed]/50 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
};

const CaptionSection = ({ element }) => {
  const setCaptionPreset = useAppStore((s) => s.setCaptionPreset);
  const updateElementProps = useAppStore((s) => s.updateElementProps);
  const { presetId, font, fontSize, animation, pill } = element.props;

  const patch = (p) => updateElementProps(element.id, p);
  const patchPill = (p) => patch({ pill: { ...pill, ...p } });

  return (
    <>
      {/* Presets */}
      <div>
        <SectionTitle>Caption Preset</SectionTitle>
        <div className="grid grid-cols-2 gap-1.5">
          {CAPTION_STYLES.map((p) => (
            <button
              key={p.id}
              data-testid={EDITOR.presetBtn(p.id)}
              onClick={() => setCaptionPreset(p.id)}
              className={`flex items-center gap-2 px-2 py-2 rounded-md border text-[11px] font-medium transition-colors ${
                presetId === p.id
                  ? "border-[#7c3aed] bg-[#7c3aed]/12 text-white"
                  : "border-[#22222c] bg-[#131318] text-[#9a9aa6] hover:border-[#7c3aed]/40"
              }`}
            >
              <span
                className="w-3.5 h-3.5 rounded-sm shrink-0 border border-white/10"
                style={{ background: getCaptionStylePreview(p.id).colorHighlight }}
              />
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* Font — the three bundled Telugu caption fonts. The backend resolves
          the selection deterministically via libass fontsdir (services/fonts.py
          :: CAPTION_FONTS) and the preview renders the same @font-face family
          from /public/fonts, so the dropdown is true WYSIWYG. Decoupled from
          the preset (Stage 5): font is chosen here, style only drives colors. */}
      <div>
        <SectionTitle>Font</SectionTitle>
        <select
          data-testid={EDITOR.fontSelect}
          value={font}
          onChange={(e) => patch({ font: e.target.value })}
          className="w-full bg-[#131318] border border-[#22222c] rounded-md px-2 py-2 text-xs text-[#d7d7de] outline-none focus:border-[#7c3aed]/60"
        >
          {CAPTION_FONTS.map((f) => (
            <option key={f} value={f} style={{ fontFamily: getCaptionFontStack(f) }}>
              {f}
            </option>
          ))}
        </select>
      </div>

      {/* Size */}
      <div>
        <SectionTitle>Size</SectionTitle>
        <input
          data-testid={EDITOR.sizeSlider}
          type="range"
          min={0.03}
          max={0.09}
          step={0.002}
          value={fontSize}
          onChange={(e) => patch({ fontSize: parseFloat(e.target.value) })}
          className="w-full accent-[#7c3aed]"
        />
      </div>

      {/* Animation — disabled: the burn path does not yet render caption
          entrance animations (BUG-001 partial fix). Kept visible with a
          "coming soon" hint, same pattern as the Font dropdown above, so the
          UI intent is preserved without silently drifting preview from export. */}
      <div>
        <SectionTitle>Animation</SectionTitle>
        <div className="flex flex-wrap gap-1.5 opacity-50 pointer-events-none select-none">
          {ANIMATIONS.map((a) => (
            <button
              key={a.id}
              data-testid={EDITOR.animationBtn(a.id)}
              disabled
              title="Caption animations coming soon — not applied in export yet."
              className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium border cursor-not-allowed ${
                a.id === "none"
                  ? "border-[#7c3aed] bg-[#7c3aed]/12 text-white"
                  : "border-[#22222c] bg-[#131318] text-[#9a9aa6]"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-[#5a5a66] mt-1.5">
          Caption animations coming soon — not applied in export yet.
        </p>
      </div>

      {/* Background pill */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <SectionTitle>Background Pill</SectionTitle>
          <button
            data-testid={EDITOR.pillToggle}
            onClick={() => patchPill({ enabled: !pill.enabled })}
            className={`relative w-8 h-4.5 rounded-full transition-colors ${
              pill.enabled ? "bg-[#7c3aed]" : "bg-[#22222c]"
            }`}
            style={{ height: 18 }}
          >
            <span
              className="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-all"
              style={{ left: pill.enabled ? 16 : 2 }}
            />
          </button>
        </div>
        {pill.enabled && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <input
                data-testid={EDITOR.pillColor}
                type="color"
                value={pill.color}
                onChange={(e) => patchPill({ color: e.target.value })}
                className="w-8 h-8 rounded cursor-pointer bg-transparent border border-[#22222c]"
              />
              <span className="text-[11px] text-[#9a9aa6] font-mono">{pill.color}</span>
            </div>
            <LabeledSlider
              testId={EDITOR.pillOpacity}
              label="Opacity" min={0} max={1} step={0.05}
              value={pill.opacity}
              onChange={(v) => patchPill({ opacity: v })}
            />
            <LabeledSlider
              testId={EDITOR.pillPadding}
              label="Padding" min={0} max={24} step={1}
              value={pill.padding}
              onChange={(v) => patchPill({ padding: v })}
            />
            <LabeledSlider
              testId={EDITOR.pillRadius}
              label="Radius" min={0} max={24} step={1}
              value={pill.radius}
              onChange={(v) => patchPill({ radius: v })}
            />
          </div>
        )}
      </div>
    </>
  );
};

const HeadlineSection = ({ element }) => {
  const updateElementProps = useAppStore((s) => s.updateElementProps);
  const p = element.props;
  const patch = (np) => updateElementProps(element.id, np);
  return (
    <div>
      <SectionTitle>Headline</SectionTitle>
      <input
        value={p.text}
        onChange={(e) => patch({ text: e.target.value })}
        className="w-full bg-[#131318] border border-[#22222c] rounded-md px-2 py-2 text-xs text-[#d7d7de] outline-none focus:border-[#7c3aed]/60 mb-2"
      />
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={p.color}
          onChange={(e) => patch({ color: e.target.value })}
          className="w-8 h-8 rounded cursor-pointer bg-transparent border border-[#22222c]"
        />
        <span className="text-[11px] text-[#9a9aa6] font-mono">{p.color}</span>
      </div>
    </div>
  );
};

const LabeledSlider = ({ label, min, max, step, value, onChange, testId }) => (
  <div>
    <div className="flex justify-between text-[10px] text-[#5a5a66] mb-1">
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
    <input
      data-testid={testId}
      type="range"
      min={min} max={max} step={step} value={value}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      className="w-full accent-[#7c3aed]"
    />
  </div>
);

/* ============================ MUSIC ============================ */

const MusicTab = () => {
  const selectedTrackId = useAppStore((s) => s.selectedTrackId);
  const setSelectedTrack = useAppStore((s) => s.setSelectedTrack);
  const musicVolume = useAppStore((s) => s.musicVolume);
  const setMusicVolume = useAppStore((s) => s.setMusicVolume);

  return (
    <>
      <div>
        <SectionTitle>Library</SectionTitle>
        <div className="space-y-1.5">
          {MUSIC_LIBRARY.map((t) => {
            const isSel = t.id === selectedTrackId;
            return (
              <button
                key={t.id}
                data-testid={EDITOR.musicItem(t.id)}
                onClick={() => setSelectedTrack(isSel ? null : t.id)}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md border text-left transition-colors ${
                  isSel
                    ? "border-[#7c3aed] bg-[#7c3aed]/12"
                    : "border-[#22222c] bg-[#131318] hover:border-[#7c3aed]/40"
                }`}
              >
                <div className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 ${isSel ? "bg-[#7c3aed]" : "bg-[#1c1c24]"}`}>
                  <Play size={11} className="text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium text-[#d7d7de] truncate">{t.name}</p>
                  <p className="text-[10px] text-[#5a5a66]">{t.mood} · {t.duration}</p>
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <SectionTitle>Music Volume</SectionTitle>
        <input
          type="range" min={0} max={100} value={musicVolume}
          onChange={(e) => setMusicVolume(parseInt(e.target.value, 10))}
          className="w-full accent-[#7c3aed]"
        />
        <p className="text-[10px] text-[#5a5a66] mt-1 font-mono">{musicVolume}%</p>
      </div>
    </>
  );
};

/* ============================ EXPORT ============================ */

const ExportTab = () => {
  const navigate = useNavigate();
  const exportSettings = useAppStore((s) => s.exportSettings);
  const setExportSetting = useAppStore((s) => s.setExportSetting);
  const currentClipId = useAppStore((s) => s.currentClipId);

  const Row = ({ label, k, options }) => (
    <div>
      <SectionTitle>{label}</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            key={o}
            onClick={() => setExportSetting(k, o)}
            className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium border transition-colors ${
              exportSettings[k] === o
                ? "border-[#7c3aed] bg-[#7c3aed]/12 text-white"
                : "border-[#22222c] bg-[#131318] text-[#9a9aa6] hover:border-[#7c3aed]/40"
            }`}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <>
      <Row label="Resolution" k="resolution" options={["720p", "1080p", "4K"]} />
      <Row label="Format" k="format" options={["mp4", "mov", "webm"]} />
      <div className="flex items-center justify-between">
        <SectionTitle>Burn-in Captions</SectionTitle>
        <button
          onClick={() => setExportSetting("burnInCaptions", !exportSettings.burnInCaptions)}
          className={`relative w-8 rounded-full transition-colors ${exportSettings.burnInCaptions ? "bg-[#7c3aed]" : "bg-[#22222c]"}`}
          style={{ height: 18 }}
        >
          <span
            className="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-all"
            style={{ left: exportSettings.burnInCaptions ? 16 : 2 }}
          />
        </button>
      </div>
      <button
        onClick={() => navigate(`/export/${currentClipId}`)}
        className="w-full py-2.5 rounded-lg bg-[#7c3aed] hover:bg-[#6d31d4] text-white text-xs font-bold tracking-wide transition-colors shadow-[0_8px_24px_rgba(124,58,237,0.35)]"
      >
        Export Clip →
      </button>
    </>
  );
};

export default Inspector;
