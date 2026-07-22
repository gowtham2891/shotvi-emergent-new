"""
Supabase JWT verification + request identity (PHASE 2 BUILD 1).

Every job-touching route depends on `get_current_user`. Identity is the
verified `sub` claim of a Supabase access token — the natural key future
billing hangs off. Workers never see client-supplied user ids: the API
resolves identity from the token and stamps it into the job record in Redis
before any Celery task is queued.

Verification material, in priority order:
  1. SUPABASE_JWT_SECRET  — legacy HS256 shared secret (Project Settings →
     API → JWT Secret). Verified locally, no network.
  2. SUPABASE_URL         — modern asymmetric keys (ES256/RS256) verified
     against the project's JWKS endpoint
     (<SUPABASE_URL>/auth/v1/.well-known/jwks.json), cached by PyJWKClient.

DEV_MODE (env, default off): ONLY consulted when NEITHER var above is set.
Then every request runs as a single fake dev user so local workflows keep
working without a Supabase project. The production path (vars present)
never reads the flag. With no vars and no DEV_MODE, job routes 401 with a
clear message — a misconfigured server fails loudly, not open.
"""

import os
from dataclasses import dataclass

import jwt as pyjwt
from fastapi import HTTPException, Request

# Read at import; tests monkeypatch these module globals directly.
SUPABASE_URL        = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
DEV_MODE            = os.getenv("DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on")

# Supabase stamps aud="authenticated" on end-user access tokens. Verifying it
# rejects other token types (anon key, service role) presented as a user.
SUPABASE_AUDIENCE = "authenticated"

DEV_USER_ID = "dev-user"

# Clock-skew tolerance for iat/exp/nbf validation. A freshly-issued token can
# carry an iat a few seconds ahead of this machine's clock; zero leeway turns
# that into ImmatureSignatureError false rejections. 10s absorbs real-world
# drift without meaningfully weakening expiry enforcement.
JWT_LEEWAY_SECONDS = 10


@dataclass(frozen=True)
class AuthUser:
    id: str            # Supabase auth.users UUID (JWT `sub`) — or DEV_USER_ID
    email: str = ""
    is_dev: bool = False  # True only for the DEV_MODE fallback identity


def auth_configured() -> bool:
    return bool(SUPABASE_JWT_SECRET or SUPABASE_URL)


_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = pyjwt.PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwks_client


def _decode(token: str) -> dict:
    """Verify signature + expiry + audience; return claims. Raises PyJWTError."""
    if SUPABASE_JWT_SECRET:
        return pyjwt.decode(
            token, SUPABASE_JWT_SECRET,
            algorithms=["HS256"], audience=SUPABASE_AUDIENCE,
            leeway=JWT_LEEWAY_SECONDS,
        )
    global _jwks_client
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    except pyjwt.exceptions.PyJWKClientError:
        # PyJWKClient caches the fetched key set; after a signing-key rotation
        # (or a failed earlier fetch) the cached set can lack the token's kid.
        # Rebuild the client once and retry so valid logins survive rotation.
        _jwks_client = None
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return pyjwt.decode(
        token, signing_key.key,
        algorithms=["ES256", "RS256"], audience=SUPABASE_AUDIENCE,
        leeway=JWT_LEEWAY_SECONDS,
    )


def _log_rejection(exc: Exception):
    """One line per rejected token — exception class + message, never token
    material. Rejections used to be silently swallowed into a generic 401,
    which made JWKS-side failures undiagnosable; keep this permanent."""
    print(f"[auth] token rejected: {type(exc).__name__}: {exc}", flush=True)


def get_current_user(request: Request) -> AuthUser:
    """FastAPI dependency: resolve the caller's verified identity.

    401 on missing/invalid/expired token. Detail strings deliberately do not
    distinguish signature failure from expiry from garbage — the client's
    remedy is the same (re-authenticate) and finer detail only helps probing.
    """
    if not auth_configured():
        if DEV_MODE:
            return AuthUser(id=DEV_USER_ID, email="dev@localhost", is_dev=True)
        raise HTTPException(
            status_code=401,
            detail="Authentication is not configured on this server. "
                   "Set SUPABASE_URL / SUPABASE_JWT_SECRET, or DEV_MODE=true for local development.",
        )

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = header[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        claims = _decode(token)
    except pyjwt.exceptions.PyJWKClientError as e:
        # JWKS unreachable or the token's kid is absent from the key set even
        # after a refresh — a server-side problem, not a bad token. This is a
        # PyJWTError subclass, so it MUST be caught before the arm below or a
        # JWKS outage masquerades as "invalid token".
        _log_rejection(e)
        raise HTTPException(status_code=401, detail="Token verification unavailable")
    except pyjwt.PyJWTError as e:
        _log_rejection(e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        # Anything else unexpected — the caller can't fix the server, but the
        # request still must not proceed unauthenticated.
        _log_rejection(e)
        raise HTTPException(status_code=401, detail="Token verification unavailable")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthUser(id=str(sub), email=str(claims.get("email") or ""))


def user_owns_job(job: dict, user: AuthUser) -> bool:
    """Ownership rule used by every job-touching route.

    Owned jobs match on the stamped owner id. Ownerless jobs are pre-auth dev
    artifacts (CLEAN SLATE decision): visible to the DEV_MODE fake user so
    local workflows keep functioning, invisible to every real user.
    Routes return 404 — not 403 — on mismatch, so strangers can't probe which
    job ids exist.
    """
    owner = (job or {}).get("owner") or ""
    if owner:
        return owner == user.id
    return user.is_dev


def log_auth_startup():
    """One clear line at API startup about which auth path is active."""
    if SUPABASE_JWT_SECRET:
        print("[auth] Supabase JWT verification: HS256 shared secret", flush=True)
    elif SUPABASE_URL:
        print(f"[auth] Supabase JWT verification: JWKS at {SUPABASE_URL}/auth/v1/.well-known/jwks.json", flush=True)
    elif DEV_MODE:
        print("=" * 68, flush=True)
        print(f"[auth] DEV MODE — no Supabase config; every request runs as "
              f"the fake user '{DEV_USER_ID}'. Never use this in production.", flush=True)
        print("=" * 68, flush=True)
    else:
        print("[auth] WARNING: no SUPABASE_URL / SUPABASE_JWT_SECRET and DEV_MODE is off — "
              "all job routes will return 401 until auth env vars are set "
              "(see SETUP_AUTH.md).", flush=True)
