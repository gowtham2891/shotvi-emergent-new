"""
FIX SPRINT 2 gate — saved caption template ("My Style") endpoints.

What must hold:
  1. Both routes require auth (same bearer guard as job routes).
  2. GET defaults to null; PUT {template: object} round-trips; PUT
     {template: null} deletes.
  3. Shape/size validation: a non-object template 422s; an oversized one 413s.
  4. Templates are per user — one user's style never leaks to another.
  5. The template rides the user:{id} hash WITHOUT disturbing billing status
     (billing reads its fields explicitly).

Auth uses the SAME real HS256 path as test_auth_ownership. Redis is an
in-memory fake (hash + string surface).
"""

import os
import sys
import time

import pytest
import jwt as pyjwt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.auth as auth
import api.database as database
import api.main as main

SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"
ALICE = "11111111-aaaa-4aaa-8aaa-111111111111"
BOB = "22222222-bbbb-4bbb-8bbb-222222222222"

TEMPLATE = {
    "name": "Punchy",
    "presetId": "hormozi",
    "font": "Ramabhadra",
    "fontSize": 0.07,
    "pill": {"enabled": True, "color": "#112233", "opacity": 0.4, "padding": 12, "radius": 10},
    "x": 0.5,
    "y": 0.3,
}


def make_token(sub=ALICE, secret=SECRET, aud="authenticated"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": aud, "email": f"{sub[:4]}@example.com", "iat": now, "exp": now + 3600},
        secret, algorithm="HS256",
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class _FakeRedis:
    """Hash + string surface used by the template and billing helpers."""

    def __init__(self):
        self.h = {}   # key -> dict
        self.kv = {}  # key -> str

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None, **kw):
        d = self.h.setdefault(key, {})
        if field is not None:
            d[field] = str(value)
        if mapping:
            d.update({k: str(v) for k, v in mapping.items()})
        if kw:
            d.update({k: str(v) for k, v in kw.items()})

    def hdel(self, key, field):
        return 1 if self.h.get(key, {}).pop(field, None) is not None else 0

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        return 1 if self.kv.pop(key, None) is not None else 0


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    # Real HS256 auth path.
    monkeypatch.setattr(auth, "SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "SUPABASE_URL", "")
    monkeypatch.setattr(auth, "DEV_MODE", False)

    fake = _FakeRedis()
    monkeypatch.setattr(database, "get_redis", lambda: fake)

    return TestClient(main.app)


# ── 1. Auth guard ─────────────────────────────────────────────

def test_routes_require_auth(client):
    assert client.get("/users/me/caption-template").status_code == 401
    assert client.put("/users/me/caption-template",
                      json={"template": TEMPLATE}).status_code == 401


# ── 2. Round-trip ─────────────────────────────────────────────

def test_get_defaults_to_null(client):
    r = client.get("/users/me/caption-template", headers=bearer(make_token()))
    assert r.status_code == 200
    assert r.json() == {"template": None}


def test_put_then_get_round_trips(client):
    tok = bearer(make_token())
    r = client.put("/users/me/caption-template", json={"template": TEMPLATE}, headers=tok)
    assert r.status_code == 200
    assert r.json()["template"] == TEMPLATE

    r = client.get("/users/me/caption-template", headers=tok)
    assert r.json()["template"] == TEMPLATE


def test_put_null_deletes(client):
    tok = bearer(make_token())
    client.put("/users/me/caption-template", json={"template": TEMPLATE}, headers=tok)
    r = client.put("/users/me/caption-template", json={"template": None}, headers=tok)
    assert r.status_code == 200
    assert r.json() == {"template": None}
    assert client.get("/users/me/caption-template", headers=tok).json() == {"template": None}


def test_put_overwrites_previous(client):
    tok = bearer(make_token())
    client.put("/users/me/caption-template", json={"template": TEMPLATE}, headers=tok)
    updated = {**TEMPLATE, "name": "Louder", "presetId": "red-pop"}
    client.put("/users/me/caption-template", json={"template": updated}, headers=tok)
    assert client.get("/users/me/caption-template", headers=tok).json()["template"] == updated


# ── 3. Validation ─────────────────────────────────────────────

def test_non_object_template_422s(client):
    tok = bearer(make_token())
    for bad in ["hormozi", 42, ["a", "b"], True]:
        r = client.put("/users/me/caption-template", json={"template": bad}, headers=tok)
        assert r.status_code == 422, bad


def test_oversized_template_413s(client):
    tok = bearer(make_token())
    huge = {"name": "x" * 10000}
    r = client.put("/users/me/caption-template", json={"template": huge}, headers=tok)
    assert r.status_code == 413


def test_corrupt_stored_value_reads_as_null(client):
    """A hand-corrupted / legacy hash field must never 500 the editor load."""
    tok = bearer(make_token())
    database.get_redis().hset(f"user:{ALICE}", "caption_template", "{not json")
    r = client.get("/users/me/caption-template", headers=tok)
    assert r.status_code == 200
    assert r.json() == {"template": None}


# ── 4. Per-user isolation ─────────────────────────────────────

def test_templates_are_per_user(client):
    alice = bearer(make_token(sub=ALICE))
    bob = bearer(make_token(sub=BOB))
    client.put("/users/me/caption-template", json={"template": TEMPLATE}, headers=alice)
    assert client.get("/users/me/caption-template", headers=bob).json() == {"template": None}
    bob_tpl = {**TEMPLATE, "name": "Bob's"}
    client.put("/users/me/caption-template", json={"template": bob_tpl}, headers=bob)
    assert client.get("/users/me/caption-template", headers=alice).json()["template"] == TEMPLATE
    assert client.get("/users/me/caption-template", headers=bob).json()["template"] == bob_tpl


# ── 5. Billing coexistence on user:{id} ───────────────────────

def test_template_field_does_not_disturb_billing_status(client):
    tok = bearer(make_token())
    client.put("/users/me/caption-template", json={"template": TEMPLATE}, headers=tok)
    r = client.get("/billing/status", headers=tok)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert "caption_template" not in body
