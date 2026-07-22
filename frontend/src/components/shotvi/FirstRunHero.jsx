import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link2, Sparkles, Loader2, UploadCloud } from "lucide-react";
import { useAppStore } from "@/store/useAppStore";
import { DASHBOARD } from "@/constants/testIds";
import { isValidYoutubeUrl } from "@/lib/youtubeUrl";

// First-run empty state (PHASE 2 BUILD 3): a brand-new user with zero
// projects sees this instead of the normal dashboard grid — one hero moment
// that gets them straight to their first clips ("4 min to first clip").
//
// Submitting here reuses the exact same job-submission path as the Upload
// page (store.submitYouTubeUrl, defaulting language to "te" — the same
// default Upload.jsx starts with). Upload.jsx picks up the in-flight job on
// mount and shows its existing step-by-step processing view, so there is no
// second progress UI to build or maintain — this hero is purely the entry
// point.
export const FirstRunHero = () => {
  const navigate = useNavigate();
  const submitYouTubeUrl = useAppStore((s) => s.submitYouTubeUrl);

  const [url, setUrl] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;

    const trimmed = url.trim();
    if (!trimmed) {
      setError("Paste a YouTube link to get started.");
      return;
    }
    // Inline validation BEFORE hitting the backend — an obviously-invalid
    // link never becomes a job that runs and fails at the download stage.
    if (!isValidYoutubeUrl(trimmed)) {
      setError("That doesn't look like a YouTube link — try a youtube.com or youtu.be URL.");
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      await submitYouTubeUrl({ url: trimmed, language: "te" });
      navigate("/upload");
    } catch (err) {
      setError(err.message || "Could not submit that link — try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      data-testid={DASHBOARD.firstRunRoot}
      className="min-h-[70vh] flex items-center justify-center"
    >
      <div className="w-full max-w-xl text-center">
        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-[#7c3aed] to-[#c026d3] flex items-center justify-center shadow-[0_10px_40px_-10px_rgba(124,58,237,0.6)]">
          <Sparkles size={28} className="text-white" />
        </div>
        <h1 className="font-display text-3xl font-bold tracking-tight mb-3">
          Paste a YouTube link to make your first clips
        </h1>
        <p className="text-sm text-[#a1a1aa] mb-8">
          We'll transcribe it, find the most shareable moments, and hand you
          ready-to-post vertical clips — usually in a few minutes.
        </p>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-[#2a2a35] bg-[#0b0b10] p-3 flex flex-col sm:flex-row gap-2"
        >
          <div className="flex-1 relative">
            <Link2
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[#71717a]"
            />
            <input
              data-testid={DASHBOARD.heroUrlInput}
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (error) setError(null);
              }}
              type="url"
              placeholder="https://youtube.com/watch?v=..."
              className="w-full bg-[#111116] border border-[#2a2a35] rounded-md py-3 pl-10 pr-3 text-sm text-white placeholder-[#5a5a66] focus:border-[#7c3aed] focus:ring-1 focus:ring-[#7c3aed] outline-none transition-colors"
            />
          </div>
          <button
            data-testid={DASHBOARD.heroSubmit}
            type="submit"
            disabled={submitting}
            className="inline-flex items-center justify-center gap-2 bg-[#7c3aed] hover:bg-[#6d28d9] disabled:opacity-60 text-white font-semibold px-6 py-3 rounded-md transition-colors shadow-[0_10px_30px_-10px_rgba(124,58,237,0.6)] whitespace-nowrap"
          >
            {submitting ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Sparkles size={15} />
            )}
            {submitting ? "Starting…" : "Make my clips"}
          </button>
        </form>

        {error && (
          <p
            data-testid={DASHBOARD.heroError}
            className="mt-3 text-sm text-[#fca5a5]"
          >
            {error}
          </p>
        )}

        <button
          onClick={() => navigate("/upload")}
          className="mt-6 inline-flex items-center gap-1.5 text-xs text-[#71717a] hover:text-white transition-colors"
        >
          <UploadCloud size={13} /> Or upload a video file instead
        </button>
      </div>
    </div>
  );
};

export default FirstRunHero;
