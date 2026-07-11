from __future__ import annotations

import json

from src.common.config import load_settings
from src.common.paths import PROJECT_ROOT, project_path


def test_project_root_is_auto_detected_from_package():
    assert PROJECT_ROOT.exists()
    assert project_path("config", "settings.yaml").exists()


def test_settings_do_not_contain_local_windows_absolute_paths():
    settings = load_settings()
    text = json.dumps(settings, ensure_ascii=False)
    assert "D:\\" not in text
    assert "C:\\" not in text
    assert "/home/" not in text


def test_raw_paths_are_relative_project_paths():
    settings = load_settings()
    for key in ["epidemic_raw", "population_raw", "weather_raw", "local_serving"]:
        value = settings["paths"][key]
        assert not value.startswith("/")
        assert ":\\" not in value
        assert project_path(value).is_absolute()
