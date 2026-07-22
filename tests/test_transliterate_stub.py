"""
POST /transliterate contract gate.

The route now proxies the IndicXlit sidecar (indicxlit/ container), but the
contract the frontend adapter (api/transliterate.js) parses is unchanged:
{text, lang} → {suggestions: [...]}. These tests pin the GRACEFUL-DEGRADE
path — with the sidecar unreachable the endpoint must return {"suggestions":
[]} exactly like the old stub, never 5xx, so editing keeps working when the
container is down. INDICXLIT_URL is pointed at a dead port to make that
deterministic even if a real sidecar is running locally.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def client(monkeypatch):
    # Force the sidecar-unreachable path: connection refused, instantly.
    monkeypatch.setenv("INDICXLIT_URL", "http://127.0.0.1:9")

    from fastapi.testclient import TestClient
    from api import main as api_main
    from api.auth import AuthUser, get_current_user

    api_main.app.dependency_overrides[get_current_user] = (
        lambda: AuthUser(id="dev-user", is_dev=True))
    yield TestClient(api_main.app)
    api_main.app.dependency_overrides.pop(get_current_user, None)


def test_transliterate_returns_suggestions_list(client):
    r = client.post("/transliterate", json={"text": "kalpavruksham", "lang": "te"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["suggestions"], list)
    # Sidecar down → no suggestions. The frontend must stay usable on [].
    assert body["suggestions"] == []


def test_transliterate_lang_defaults_to_te(client):
    r = client.post("/transliterate", json={"text": "mind"})
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_transliterate_missing_text_is_422(client):
    r = client.post("/transliterate", json={"lang": "te"})
    assert r.status_code == 422
