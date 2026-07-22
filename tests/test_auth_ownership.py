"""
PHASE 2 BUILD 1 gate — Supabase JWT auth + job ownership.

What must hold:
  1. Token validation: valid → request runs as the token's sub; absent /
     garbage / expired / wrong-signature / wrong-audience → 401.
  2. Job creation stamps the verified caller as owner (never client-supplied).
  3. Every job-touching route: owner → normal behaviour; stranger → 404
     (NOT 403 — existence of other users' jobs must not leak).
  4. GET /jobs lists only the caller's jobs.
  5. Video-id-keyed resources (/transcript, /clips/download) follow the
     by-video ownership rule.
  6. DEV_MODE fallback: with NO Supabase config and DEV_MODE=true every
     request runs as the fake dev user and pre-auth ownerless jobs stay
     visible; with no config and DEV_MODE off, requests 401 — the flag is
     never consulted when config is present.

Tokens are real HS256 JWTs minted with a test secret; verification runs the
REAL api.auth code path (no dependency override here — that's the point).
The Redis job store is replaced with an in-memory dict, house style.
"""

import os
import sys
import time

import pytest
import jwt as pyjwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.auth as auth
import api.main as main
from api.auth import AuthUser, user_owns_job
from api.database import _owner_matches

SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"
ALICE = "11111111-aaaa-4aaa-8aaa-111111111111"
BOB   = "22222222-bbbb-4bbb-8bbb-222222222222"

YT_URL = "https://youtu.be/vidAAAAAAAA"


def make_token(sub=ALICE, secret=SECRET, aud="authenticated",
               exp_offset=3600, email="alice@example.com", iat_offset=0):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": aud, "email": email,
         "iat": now + iat_offset, "exp": now + exp_offset},
        secret, algorithm="HS256",
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeTask:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def set(self, k, v, ex=None):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """TestClient with REAL HS256 verification and an in-memory job store."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)

    store = {}

    def fake_create_job(job_id, url, language="te", owner=""):
        store[job_id] = {
            "job_id": job_id, "url": url, "language": language, "owner": owner,
            "status": "pending", "progress": 0, "current_stage": "queued",
            "video_id": "", "error": "", "clips": [],
            "captioned_path": "", "vertical_path": "",
            "created_at": f"{len(store):06d}",
        }
        return store[job_id]

    def fake_update_job(job_id, **kw):
        store[job_id].update(kw)

    def fake_list(owner, include_ownerless=False):
        return [j for j in store.values()
                if not j["url"].startswith("rerender:")
                and _owner_matches(j, owner, include_ownerless)]

    def fake_video_owned_by(video_id, owner, include_ownerless=False):
        return any(j.get("video_id") == video_id
                   and _owner_matches(j, owner, include_ownerless)
                   for j in store.values())

    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    uploads.mkdir()
    outputs.mkdir()

    monkeypatch.setattr(main, "create_job", fake_create_job)
    monkeypatch.setattr(main, "get_job", lambda jid: store.get(jid))
    monkeypatch.setattr(main, "update_job", fake_update_job)
    monkeypatch.setattr(main, "get_job_by_video_id", lambda vid, **kw: None)
    monkeypatch.setattr(main, "_recover_from_storage", lambda vid, owner="": None)
    monkeypatch.setattr(main, "list_jobs_by_owner", fake_list)
    monkeypatch.setattr(main, "video_owned_by", fake_video_owned_by)
    monkeypatch.setattr(main, "process_video", _FakeTask())
    monkeypatch.setattr(main, "rerender_clip", _FakeTask())
    monkeypatch.setattr(main, "get_redis", lambda: _FakeRedis())
    # No pipeline is ever in flight in these tests (FIX SPRINT 1 lock pre-check).
    monkeypatch.setattr(main, "video_lock_held", lambda vid: False)
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(main, "OUTPUT_DIR", outputs)

    yield TestClient(main.app), store, uploads, outputs


def _submit_job(tc, sub=ALICE):
    return tc.post("/jobs", json={"url": YT_URL}, headers=bearer(make_token(sub=sub)))


# ── 1. Token validation ─────────────────────────────────────────────────────

def test_absent_token_401(client):
    tc, *_ = client
    assert tc.post("/jobs", json={"url": YT_URL}).status_code == 401


def test_garbage_token_401(client):
    tc, *_ = client
    r = tc.post("/jobs", json={"url": YT_URL},
                headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_expired_token_401(client):
    tc, *_ = client
    r = tc.post("/jobs", json={"url": YT_URL},
                headers=bearer(make_token(exp_offset=-120)))
    assert r.status_code == 401


def test_wrong_signature_401(client):
    tc, *_ = client
    r = tc.post("/jobs", json={"url": YT_URL},
                headers=bearer(make_token(secret="wrong-secret-0123456789abcdef0123456789abcdef")))
    assert r.status_code == 401


def test_wrong_audience_401(client):
    # e.g. a service-role or anon token presented as a user token
    tc, *_ = client
    r = tc.post("/jobs", json={"url": YT_URL},
                headers=bearer(make_token(aud="anon")))
    assert r.status_code == 401


def test_minor_clock_skew_iat_accepted_within_leeway(client):
    # A freshly-issued token whose iat sits a few seconds ahead of local time
    # (normal network clock drift) must NOT be rejected as immature.
    tc, *_ = client
    r = tc.get("/jobs", headers=bearer(make_token(iat_offset=5)))
    assert r.status_code == 200


def test_iat_far_in_future_still_rejected(client):
    # Leeway absorbs drift, it does not disable the check.
    tc, *_ = client
    r = tc.get("/jobs", headers=bearer(make_token(iat_offset=300)))
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


def test_valid_token_creates_job(client):
    tc, store, *_ = client
    r = _submit_job(tc)
    assert r.status_code == 200
    assert r.json()["job_id"] in store


# ── 2. Creation stamps the verified owner ───────────────────────────────────

def test_job_creation_stamps_owner_from_token(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    assert store[job_id]["owner"] == ALICE


# ── 3. Ownership on job routes: owner OK, stranger 404 ─────────────────────

def test_owner_can_poll_stranger_gets_404(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]

    assert tc.get(f"/jobs/{job_id}", headers=bearer(make_token(sub=ALICE))).status_code == 200
    r = tc.get(f"/jobs/{job_id}", headers=bearer(make_token(sub=BOB)))
    assert r.status_code == 404          # not 403 — do not leak existence


def test_stranger_cannot_patch_job(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    r = tc.patch(f"/jobs/{job_id}", json={"email": "bob@evil.example"},
                 headers=bearer(make_token(sub=BOB)))
    assert r.status_code == 404
    assert "email" not in store[job_id]


def test_stranger_cannot_rerender(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    store[job_id].update(video_id="vidAAAAAAAA",
                         clips=[{"clip_id": "c1", "raw_path": "x.mp4"}])
    r = tc.post(f"/jobs/{job_id}/clips/0/rerender", json={},
                headers=bearer(make_token(sub=BOB)))
    assert r.status_code == 404


def test_owner_rerender_stamps_owner_on_rerender_job(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    store[job_id].update(video_id="vidAAAAAAAA",
                         clips=[{"clip_id": "c1", "raw_path": "x.mp4"}])
    r = tc.post(f"/jobs/{job_id}/clips/0/rerender", json={},
                headers=bearer(make_token(sub=ALICE)))
    assert r.status_code == 200
    rr_id = r.json()["rerender_job_id"]
    assert store[rr_id]["owner"] == ALICE


def test_stranger_cannot_touch_drafts(client):
    tc, store, *_ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    save = tc.patch(f"/jobs/{job_id}/clips/c1/draft", json={"a": 1},
                    headers=bearer(make_token(sub=BOB)))
    load = tc.get(f"/jobs/{job_id}/clips/c1/draft",
                  headers=bearer(make_token(sub=BOB)))
    assert save.status_code == 404
    assert load.status_code == 404


# ── 4. Job list is scoped to the caller ─────────────────────────────────────

def test_list_shows_only_own_jobs(client):
    tc, store, *_ = client
    a1 = _submit_job(tc, sub=ALICE).json()["job_id"]
    a2 = _submit_job(tc, sub=ALICE).json()["job_id"]
    b1 = _submit_job(tc, sub=BOB).json()["job_id"]

    alice_sees = {j["job_id"] for j in
                  tc.get("/jobs", headers=bearer(make_token(sub=ALICE))).json()}
    bob_sees = {j["job_id"] for j in
                tc.get("/jobs", headers=bearer(make_token(sub=BOB))).json()}

    assert alice_sees == {a1, a2}
    assert bob_sees == {b1}


def test_list_requires_auth(client):
    tc, *_ = client
    assert tc.get("/jobs").status_code == 401


# ── 5. Video-id-keyed resources follow by-video ownership ──────────────────

def test_transcript_scoped_by_video_ownership(client):
    tc, store, uploads, _ = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    store[job_id]["video_id"] = "vidAAAAAAAA"
    (uploads / "vidAAAAAAAA_audio_transcript.json").write_text(
        '{"sentences": [], "words": []}', encoding="utf-8")

    ok = tc.get("/transcript/vidAAAAAAAA", headers=bearer(make_token(sub=ALICE)))
    no = tc.get("/transcript/vidAAAAAAAA", headers=bearer(make_token(sub=BOB)))
    assert ok.status_code == 200
    assert no.status_code == 404


def test_download_scoped_by_video_ownership(client):
    tc, store, _, outputs = client
    job_id = _submit_job(tc, sub=ALICE).json()["job_id"]
    store[job_id]["video_id"] = "vidAAAAAAAA"
    clip = outputs / "vidAAAAAAAA_clip1_hook_captioned.mp4"
    clip.write_bytes(b"fake mp4")

    ok = tc.get("/clips/download", params={"path": str(clip)},
                headers=bearer(make_token(sub=ALICE)))
    no = tc.get("/clips/download", params={"path": str(clip)},
                headers=bearer(make_token(sub=BOB)))
    absent = tc.get("/clips/download", params={"path": str(clip)})
    assert ok.status_code == 200
    assert no.status_code == 404
    assert absent.status_code == 401


# ── 6. DEV_MODE fallback ────────────────────────────────────────────────────

def test_no_config_no_dev_mode_401(client, monkeypatch):
    tc, *_ = client
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "")
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)
    assert tc.get("/jobs").status_code == 401


def test_dev_mode_assumes_fake_user_and_sees_ownerless_jobs(client, monkeypatch):
    tc, store, *_ = client
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "")
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", True)

    # Pre-auth dev artifact: no owner stamped.
    store["legacy-1"] = {
        "job_id": "legacy-1", "url": "recovered:oldvid", "language": "te",
        "owner": "", "status": "done", "progress": 100, "current_stage": "Complete",
        "video_id": "oldvid", "error": "", "clips": [],
        "captioned_path": "", "vertical_path": "", "created_at": "000000",
    }

    # No Authorization header anywhere — dev identity is assumed.
    listed = tc.get("/jobs")
    assert listed.status_code == 200
    assert {j["job_id"] for j in listed.json()} == {"legacy-1"}
    assert tc.get("/jobs/legacy-1").status_code == 200

    created = tc.post("/jobs", json={"url": YT_URL})
    assert created.status_code == 200
    assert store[created.json()["job_id"]]["owner"] == auth.DEV_USER_ID


def test_dev_mode_ignored_when_auth_configured(client, monkeypatch):
    # Vars present + DEV_MODE on → production path: token still required.
    tc, *_ = client
    monkeypatch.setattr(auth, "DEV_MODE", True)   # secret stays set (fixture)
    assert tc.get("/jobs").status_code == 401
    assert tc.get("/jobs", headers=bearer(make_token(sub=ALICE))).status_code == 200


# ── 7. ES256 / JWKS path — the shape of a REAL Supabase access token ────────
#
# New Supabase projects sign with asymmetric ES256 keys; the token carries a
# kid resolved against the project JWKS. This section was missing when the
# JWKS path shipped — every earlier token test minted HS256, so a bug on the
# ES256 branch could never fail a test.

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

ES_KID = "4da8a286-c82b-4e51-98c7-287419afd2df"
ES_ISS = "https://egfaahhkfmrqbcjovnie.supabase.co/auth/v1"


def make_es256_token(key, sub=ALICE, kid=ES_KID, aud="authenticated",
                     exp_offset=3600, email="alice@example.com"):
    """Mirror a genuine Supabase access token: header + full claim set."""
    now = int(time.time())
    return pyjwt.encode(
        {
            "iss": ES_ISS, "sub": sub, "aud": aud,
            "exp": now + exp_offset, "iat": now,
            "email": email, "phone": "",
            "app_metadata": {"provider": "email", "providers": ["email"]},
            "user_metadata": {"email": email, "email_verified": True},
            "role": "authenticated", "aal": "aal1",
            "amr": [{"method": "password", "timestamp": now}],
            "session_id": "6b4f7b0e-3e63-4bb2-a2ad-11122f11f111",
            "is_anonymous": False,
        },
        key, algorithm="ES256", headers={"kid": kid, "typ": "JWT"},
    )


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """Stands in for PyJWKClient: kid-keyed lookup, same error contract."""
    def __init__(self, keys_by_kid):
        self.keys_by_kid = keys_by_kid

    def get_signing_key_from_jwt(self, token):
        kid = pyjwt.get_unverified_header(token).get("kid")
        if kid not in self.keys_by_kid:
            raise pyjwt.exceptions.PyJWKClientError(
                f'Unable to find a signing key that matches: "{kid}"')
        return _FakeSigningKey(self.keys_by_kid[kid])


@pytest.fixture
def es256_key(monkeypatch):
    """Switch auth to the JWKS/ES256 path with a locally-generated key."""
    key = generate_private_key(SECP256R1())
    fake = _FakeJWKSClient({ES_KID: key.public_key()})
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "")
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(auth, "_jwks_client", fake)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: fake)
    return key


def test_valid_es256_supabase_token_accepted(client, es256_key):
    # THE regression case: ES256, matching kid, correct iss/aud, not expired,
    # full Supabase claim set — must verify and run as the token's sub.
    tc, store, *_ = client
    r = tc.post("/jobs", json={"url": YT_URL},
                headers=bearer(make_es256_token(es256_key)))
    assert r.status_code == 200
    assert store[r.json()["job_id"]]["owner"] == ALICE


def test_es256_expired_401(client, es256_key):
    tc, *_ = client
    r = tc.get("/jobs", headers=bearer(make_es256_token(es256_key, exp_offset=-120)))
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


def test_es256_wrong_audience_401(client, es256_key):
    tc, *_ = client
    r = tc.get("/jobs", headers=bearer(make_es256_token(es256_key, aud="anon")))
    assert r.status_code == 401


def test_es256_wrong_signature_401(client, es256_key):
    # Same kid, different private key — signature must not verify.
    tc, *_ = client
    impostor = generate_private_key(SECP256R1())
    r = tc.get("/jobs", headers=bearer(make_es256_token(impostor)))
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


def test_es256_unknown_kid_reports_unavailable_not_invalid(client, es256_key, monkeypatch):
    # A kid the JWKS can't resolve (even after refresh) is a server-side
    # verification problem — it must not read as a bad client token.
    tc, *_ = client
    r = tc.get("/jobs", headers=bearer(
        make_es256_token(es256_key, kid="00000000-0000-0000-0000-000000000000")))
    assert r.status_code == 401
    assert r.json()["detail"] == "Token verification unavailable"


def test_es256_stale_jwks_refreshed_once_after_rotation(monkeypatch):
    # Signing-key rotation: the cached key set lacks the new kid; _decode must
    # rebuild the JWKS client once and succeed, not 401 the valid login.
    key = generate_private_key(SECP256R1())
    stale = _FakeJWKSClient({})
    fresh = _FakeJWKSClient({ES_KID: key.public_key()})
    clients = iter([stale, fresh])
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", "")
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(auth, "_jwks_client", None)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: next(clients))
    claims = auth._decode(make_es256_token(key))
    assert claims["sub"] == ALICE


# ── Ownership predicate unit tests ──────────────────────────────────────────

def test_user_owns_job_matrix():
    alice = AuthUser(id=ALICE)
    dev = AuthUser(id=auth.DEV_USER_ID, is_dev=True)
    owned = {"owner": ALICE}
    ownerless = {"owner": ""}
    assert user_owns_job(owned, alice)
    assert not user_owns_job(owned, AuthUser(id=BOB))
    assert not user_owns_job(owned, dev)          # dev sees ownerless ONLY
    assert user_owns_job(ownerless, dev)
    assert not user_owns_job(ownerless, alice)    # clean slate for real users


def test_owner_matches_mirrors_user_owns_job():
    assert _owner_matches({"owner": ALICE}, ALICE, False)
    assert not _owner_matches({"owner": ALICE}, BOB, False)
    assert not _owner_matches({"owner": ALICE}, BOB, True)
    assert _owner_matches({"owner": ""}, "anything", True)
    assert not _owner_matches({"owner": ""}, ALICE, False)
