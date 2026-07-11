// localStorage registry of submitted jobs — the backend has no job-list
// endpoint (jobs live in Redis, fetchable by id only, 24h TTL), so this is
// the dashboard's only memory of past projects. Known temporary limitation:
// entries outlive their jobs and are shown as "expired" once GET /jobs/{id}
// 404s.

const KEY = "shotvi.projects.v1";

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function write(list) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // Storage full/unavailable — registry is best-effort
  }
}

export function listProjects() {
  return read().sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
}

// entry: { jobId, title, language, source: 'upload'|'youtube', createdAt, videoId? }
export function upsertProject(entry) {
  const list = read();
  const idx = list.findIndex((p) => p.jobId === entry.jobId);
  if (idx >= 0) list[idx] = { ...list[idx], ...entry };
  else list.push({ createdAt: Date.now(), ...entry });
  write(list);
  return entry;
}

export function removeProject(jobId) {
  write(read().filter((p) => p.jobId !== jobId));
}

export function getProjectEntry(jobId) {
  return read().find((p) => p.jobId === jobId) || null;
}
