/**
 * Feature #5 — auto hook title.
 *
 * A clean clip opens with its headline element pre-filled from the AI clip
 * selector's hook_text (ClipOut.hook_text → UI clip.hook) and made visible,
 * so the strongest line is already on the canvas as a burnable overlay. The
 * user can edit or hide it like any element, and a saved draft's elements
 * (including its own headline state) always overwrite this afterwards —
 * openClip applies the draft AFTER this runs, so re-opened edited clips
 * never get clobbered.
 *
 * uppercase is forced off: Telugu has no letter case, and uppercasing only
 * the embedded English tokens of a mixed hook reads wrong.
 */
export function applyHookHeadline(elements, hook) {
  const text = (hook || "").trim();
  if (!text) return elements;
  return elements.map((el) =>
    el.type === "headline"
      ? {
          ...el,
          visible: true,
          props: { ...el.props, text, uppercase: false },
        }
      : el
  );
}
