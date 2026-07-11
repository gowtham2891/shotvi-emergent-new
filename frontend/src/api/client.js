import axios from "axios";

// Base URL for the Shotvi FastAPI backend. Override via frontend .env —
// never hardcode deployment URLs here.
export const API_BASE_URL = (
  process.env.REACT_APP_API_BASE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

// Offline dev path: when true, store actions serve mockData instead of
// touching the network. Default is the real API.
export const USE_MOCKS = process.env.REACT_APP_USE_MOCKS === "true";

export const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
});

export class ApiError extends Error {
  constructor(message, { status = null, detail = null, cause = null, retryable = false } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status; // HTTP status, null for network-level failures
    this.detail = detail; // FastAPI `detail` payload when present
    this.cause = cause;
    this.retryable = retryable;
  }
}

// Normalize axios/network/FastAPI errors into a single shape the store can
// surface to the user (toast/inline) and use to decide retryability.
export function toApiError(err, fallback = "Request failed") {
  if (err instanceof ApiError) return err;
  if (axios.isAxiosError(err)) {
    const status = err.response?.status ?? null;
    const detail = err.response?.data?.detail ?? null;
    if (err.code === "ECONNABORTED") {
      return new ApiError("Request timed out — is the backend running?", {
        status, detail, cause: err, retryable: true,
      });
    }
    if (!err.response) {
      return new ApiError(
        `Cannot reach the Shotvi backend at ${API_BASE_URL}`,
        { cause: err, retryable: true }
      );
    }
    return new ApiError(typeof detail === "string" ? detail : fallback, {
      status, detail, cause: err, retryable: status >= 500,
    });
  }
  return new ApiError(err?.message || fallback, { cause: err });
}

// ── File URL helpers ─────────────────────────────────────────────
// The backend returns raw server filesystem paths (e.g.
// "storage\outputs\<file>.mp4"). Files are reachable by basename via the
// static /outputs mount and the /thumbnails route.

export const pathBasename = (p) => (p ? String(p).split(/[\\/]/).pop() : "");

export const outputFileUrl = (p) =>
  p ? `${API_BASE_URL}/outputs/${encodeURIComponent(pathBasename(p))}` : null;

export const thumbnailFileUrl = (p) =>
  p ? `${API_BASE_URL}/thumbnails/${encodeURIComponent(pathBasename(p))}` : null;

// GET /clips/download expects the full backend filesystem path, not a basename.
export const downloadFileUrl = (p) =>
  p ? `${API_BASE_URL}/clips/download?path=${encodeURIComponent(p)}` : null;
