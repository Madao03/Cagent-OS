import base64
import sqlite3
from unittest.mock import Mock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cagent_os.auth.user_llm_key_store import KeyStoreUnavailable, UserLLMKeyStore
from cagent_os.interfaces.http.routes_llm_keys import build_llm_keys_router


def test_hex_and_fernet_secrets_read_the_same_database(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    path = tmp_path / "keys.db"
    monkeypatch.setenv("CAGENTOS_KEY_ENCRYPTION_SECRET", base64.urlsafe_b64decode(key).hex())
    store = UserLLMKeyStore(path)
    store.upsert("alice", provider="deepseek", api_key="test-key", default_model="deepseek-flash")
    monkeypatch.setenv("CAGENTOS_KEY_ENCRYPTION_SECRET", key.decode())
    assert UserLLMKeyStore(path).get("alice").api_key == "test-key"
    with sqlite3.connect(path) as conn:
        ciphertext = conn.execute("select api_key_encrypted from user_llm_keys").fetchone()[0]
    assert Fernet(key).decrypt(ciphertext) == b"test-key"


@pytest.mark.parametrize("secret", ["", "invalid"])
def test_disabled_storage_does_not_accept_keys(tmp_path, monkeypatch, secret):
    monkeypatch.setenv("CAGENTOS_KEY_ENCRYPTION_SECRET", secret)
    store = UserLLMKeyStore(tmp_path / "keys.db")
    with pytest.raises(KeyStoreUnavailable):
        store.upsert("alice", provider="deepseek", api_key="test-key")
    assert store.get("alice") is None


def test_probe_uses_form_without_overwriting_saved_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("CAGENTOS_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())
    store = UserLLMKeyStore(tmp_path / "keys.db")
    store.upsert("alice", provider="deepseek", api_key="saved-key", default_model="original")
    app = FastAPI()
    registry = Mock()
    app.include_router(build_llm_keys_router(store, registry))
    client = TestClient(app)
    with patch("cagent_os.interfaces.http.routes_llm_keys.require_principal_id", return_value="alice"):
        for key in ["", "trial-key"]:
            response = client.post("/api/v1/llm/test", json={
                "provider": "deepseek", "api_key": key, "default_model": "trial-model",
            })
            assert response.json()["ok"]
            config = registry.probe_backend.call_args.args[1]
            assert config.api_key == (key or "saved-key")
            assert registry.probe_backend.return_value.complete.call_args.args[0].model == "trial-model"
        assert client.post("/api/v1/llm/test", json={
            "provider": "openai", "api_key": "", "default_model": "trial",
        }).status_code == 400
    assert store.get("alice").default_model == "original"
    assert store.get("alice").api_key == "saved-key"
