import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, MoreVertical, Play, Clock, Sparkles, TrendingUp, Trash2, FileVideo } from "lucide-react";
import { AppShell } from "@/components/shotvi/AppShell";
import { StatusBadge } from "@/components/shotvi/StatusBadge";
import { FirstRunHero } from "@/components/shotvi/FirstRunHero";
import { useAppStore } from "@/store/useAppStore";
import { DASHBOARD } from "@/constants/testIds";
import { LANGUAGES } from "@/data/mockData";

const langLabel = (code) =>
  LANGUAGES.find((l) => l.code === code)?.flag || code.toUpperCase();

const ProjectCard = ({ project, onOpen, onRemove }) => {
  return (
    <div
      data-testid={DASHBOARD.projectCard(project.id)}
      className="group rounded-xl border border-[#2a2a35] bg-[#0b0b10] overflow-hidden hover:border-[#7c3aed]/50 transition-all cursor-pointer"
      onClick={() => onOpen(project)}
    >
      <div className="relative aspect-video overflow-hidden bg-[#111116]">
        {project.thumbnail ? (
          <img
            src={project.thumbnail}
            alt={project.title}
            className="w-full h-full object-cover opacity-90 group-hover:opacity-100 group-hover:scale-105 transition-all duration-500"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-[#111116] to-[#1a1a24]">
            <FileVideo size={28} className="text-[#2a2a35]" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
        <div className="absolute top-3 left-3">
          <StatusBadge status={project.status} progress={project.progress} />
        </div>
        <div className="absolute top-3 right-3 flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-full bg-black/60 backdrop-blur-sm border border-white/10">
          <span className="text-[#a1a1aa]">{langLabel(project.language)}</span>
        </div>
        <div className="absolute bottom-3 left-3 text-[11px] font-mono text-white/90 flex items-center gap-1.5 bg-black/50 px-2 py-1 rounded backdrop-blur-sm">
          <Clock size={11} /> {project.duration}
        </div>
        {project.status === "ready" && (
          <button
            data-testid={DASHBOARD.projectOpen(project.id)}
            className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <div className="w-14 h-14 rounded-full bg-[#7c3aed] flex items-center justify-center shadow-[0_0_30px_rgba(124,58,237,0.7)]">
              <Play size={20} className="text-white ml-0.5" fill="white" />
            </div>
          </button>
        )}
      </div>

      <div className="p-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 className="font-semibold text-sm text-white leading-snug line-clamp-2 flex-1">
            {project.title}
          </h3>
          {project.status === "expired" || project.status === "failed" ? (
            <button
              title="Remove from dashboard"
              className="text-[#71717a] hover:text-[#ef4444] p-1 -mr-1"
              onClick={(e) => {
                e.stopPropagation();
                onRemove(project);
              }}
            >
              <Trash2 size={15} />
            </button>
          ) : (
            <button
              className="text-[#71717a] hover:text-white p-1 -mr-1"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreVertical size={15} />
            </button>
          )}
        </div>
        <div className="flex items-center justify-between text-[11px] text-[#71717a]">
          <span>{project.createdAt}</span>
          {project.clipsCount > 0 ? (
            <span className="inline-flex items-center gap-1 text-[#a78bfa]">
              <Sparkles size={11} /> {project.clipsCount} clips ready
            </span>
          ) : project.status === "expired" ? (
            <span className="text-[#f59e0b]">Expired</span>
          ) : project.status === "failed" ? (
            <span className="text-[#ef4444]">Failed</span>
          ) : (
            <span>Processing...</span>
          )}
        </div>
        {(project.status === "expired" || project.status === "failed") && project.error && (
          <p className="mt-2 text-[11px] text-[#71717a] leading-snug line-clamp-2">
            {project.error}
          </p>
        )}

        {typeof project.progress === "number" &&
          project.status !== "ready" && (
            <div className="mt-3 h-1 rounded-full bg-[#1a1a24] overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-[#7c3aed] to-[#c026d3] rounded-full transition-all"
                style={{ width: `${project.progress}%` }}
              />
            </div>
          )}
      </div>
    </div>
  );
};

export default function Dashboard() {
  const projects = useAppStore((s) => s.projects);
  const projectsLoading = useAppStore((s) => s.projectsLoading);
  const loadProjects = useAppStore((s) => s.loadProjects);
  const removeProjectEntry = useAppStore((s) => s.removeProjectEntry);
  const navigate = useNavigate();

  // Hydrate from the localStorage job registry (backend has no list endpoint)
  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const onOpen = (project) => {
    if (project.status === "expired") return; // nothing to open
    navigate(`/clips/${project.id}`);
  };

  const onRemove = (project) => removeProjectEntry(project.id);

  const readyClips = projects.reduce((a, p) => a + p.clipsCount, 0);
  const processing = projects.filter((p) => p.status !== "ready").length;

  // First-run detection: zero jobs for this user. Only decided once the
  // initial load settles — while projectsLoading is true we don't yet know,
  // so returning users never see a flash of the hero before their projects
  // arrive, and first-time users just see the existing loading state briefly
  // instead of the hero flashing in twice.
  const isFirstRun = !projectsLoading && projects.length === 0;

  return (
    <AppShell
      title="Projects"
      subtitle={isFirstRun ? "Let's make your first clip" : "Manage your uploads, clips and exports"}
      actions={
        !isFirstRun && (
          <button
            data-testid={DASHBOARD.newProject}
            onClick={() => navigate("/upload")}
            className="inline-flex items-center gap-1.5 bg-[#7c3aed] hover:bg-[#6d28d9] text-white text-sm font-semibold px-4 py-2 rounded-md transition-colors shadow-[0_8px_24px_-8px_rgba(124,58,237,0.7)]"
          >
            <Plus size={15} /> New Project
          </button>
        )
      }
    >
      <div
        data-testid={DASHBOARD.root}
        className="p-8 max-w-[1400px] mx-auto"
      >
        {isFirstRun ? (
          <FirstRunHero />
        ) : (
          <>
            {/* Stats */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
              {[
                {
                  l: "Total projects",
                  v: projects.length,
                  i: Sparkles,
                  c: "#7c3aed",
                },
                {
                  l: "Clips generated",
                  v: readyClips,
                  i: TrendingUp,
                  c: "#10b981",
                },
                {
                  l: "Processing",
                  v: processing,
                  i: Clock,
                  c: "#f59e0b",
                },
                {
                  l: "This month usage",
                  v: "42%",
                  i: Play,
                  c: "#c026d3",
                },
              ].map((s) => {
                const Icon = s.i;
                return (
                  <div
                    key={s.l}
                    className="rounded-xl border border-[#2a2a35] bg-[#0b0b10] p-5"
                  >
                    <div className="flex items-center justify-between mb-4">
                      <p className="text-[11px] uppercase tracking-widest text-[#71717a]">
                        {s.l}
                      </p>
                      <div
                        className="w-8 h-8 rounded-md flex items-center justify-center"
                        style={{
                          backgroundColor: `${s.c}20`,
                          color: s.c,
                        }}
                      >
                        <Icon size={15} />
                      </div>
                    </div>
                    <p className="font-display text-3xl font-bold text-white">
                      {s.v}
                    </p>
                  </div>
                );
              })}
            </div>

            {/* Section header */}
            <div className="flex items-end justify-between mb-5">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight">
                  Recent projects
                </h2>
                <p className="text-xs text-[#71717a] mt-1">
                  {projects.length} total · Sorted by most recent
                </p>
              </div>
              <div className="flex gap-2 text-xs">
                {["All", "Ready", "Processing", "Failed"].map((f, i) => (
                  <button
                    key={f}
                    className={`px-3 py-1.5 rounded-md border transition-colors ${
                      i === 0
                        ? "bg-[#7c3aed]/15 border-[#7c3aed]/40 text-white"
                        : "bg-[#0b0b10] border-[#2a2a35] text-[#a1a1aa] hover:text-white"
                    }`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            {/* Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              <button
                data-testid={DASHBOARD.newProject + "-tile"}
                onClick={() => navigate("/upload")}
                className="rounded-xl border-2 border-dashed border-[#2a2a35] bg-[#0b0b10]/50 hover:border-[#7c3aed] hover:bg-[#7c3aed]/5 transition-colors min-h-[280px] flex flex-col items-center justify-center gap-3 text-[#a1a1aa] hover:text-white"
              >
                <div className="w-12 h-12 rounded-full bg-[#7c3aed]/15 border border-[#7c3aed]/30 flex items-center justify-center">
                  <Plus size={22} />
                </div>
                <div className="text-center">
                  <p className="font-display font-semibold text-base">
                    New project
                  </p>
                  <p className="text-xs text-[#71717a] mt-1">
                    Upload video or paste YouTube URL
                  </p>
                </div>
              </button>

              {projects.map((p) => (
                <ProjectCard key={p.id} project={p} onOpen={onOpen} onRemove={onRemove} />
              ))}
              {projectsLoading && projects.length === 0 && (
                <div className="rounded-xl border border-[#2a2a35] bg-[#0b0b10] min-h-[280px] flex items-center justify-center text-sm text-[#71717a]">
                  Loading projects…
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
