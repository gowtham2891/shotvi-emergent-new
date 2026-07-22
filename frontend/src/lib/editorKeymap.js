// THE editor keyboard map — one pure decision function, consumed by the ONE
// global keydown listener (CanvasArea). Space play/pause silently broke when
// two independent window listeners with separate typing guards coexisted
// (CanvasArea: Space-as-pan/Escape/Delete/Arrows; Editor.jsx: Ctrl+Z/Y) and
// neither actually bound Space→togglePlay. All key precedence and the single
// typing guard live here now, where a unit test can pin them.
//
// `isEditing` = isTextEditingTarget(document.activeElement). When true,
// EVERY key passes through to the focused input: Space types a space,
// Backspace edits/merges via the input's own handler, Ctrl+Z is the
// browser's native typing undo — the document never hijacks them.

export function resolveEditorKey(e, isEditing) {
  if (isEditing) return { action: "passthrough" };

  const mod = e.ctrlKey || e.metaKey;
  if (mod) {
    const k = typeof e.key === "string" ? e.key.toLowerCase() : "";
    if (k === "y" || (k === "z" && e.shiftKey)) return { action: "redo", preventDefault: true };
    if (k === "z") return { action: "undo", preventDefault: true };
    return { action: "passthrough" }; // other browser combos stay native
  }

  if (e.code === "Space") {
    // preventDefault in both cases: stops page scroll AND stops a still-
    // focused button (e.g. the Play button the user just clicked) from ALSO
    // activating on Space, which would double-toggle playback. Held-key
    // auto-repeats must not re-toggle — they only keep the space+drag pan
    // modifier armed.
    return e.repeat
      ? { action: "armPan", preventDefault: true }
      : { action: "togglePlay", preventDefault: true };
  }
  if (e.key === "Escape") return { action: "clearSelection" };
  if (e.key === "Delete" || e.key === "Backspace") return { action: "deleteSelected" };
  if (typeof e.key === "string" && e.key.startsWith("Arrow")) return { action: "nudge" };
  return { action: "passthrough" };
}
