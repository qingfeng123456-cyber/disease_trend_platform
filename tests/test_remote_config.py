from __future__ import annotations

from src.common.paths import project_path
from src.remote.config import clone_without_secrets, load_remote_config


def test_remote_example_config_loads_without_password():
    config = load_remote_config("config/remote_cluster.example.yaml", ".env.example")
    assert config["remote"]["host"] == "192.168.1.100"
    assert config["remote"]["password"] in {None, ""}


def test_sanitize_config_masks_secret_values():
    cleaned = clone_without_secrets({"remote": {"password": "secret", "key_passphrase": "pass"}})
    assert cleaned["remote"]["password"] == "***"
    assert cleaned["remote"]["key_passphrase"] == "***"


def test_real_remote_config_is_gitignored():
    text = project_path(".gitignore").read_text(encoding="utf-8")
    assert "config/remote_cluster.yaml" in text
    assert ".env" in text
