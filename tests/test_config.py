from src.common.config import get_setting, load_settings
from src.common.paths import PROJECT_ROOT, project_path, safe_relative


def test_config_reading():
    settings = load_settings()
    assert get_setting(settings, "project.name") == "disease_trend_platform"
    assert get_setting(settings, "web.port") == 5000


def test_project_paths():
    assert project_path("config", "settings.yaml").exists()
    assert PROJECT_ROOT.name == "disease_trend_platform"
    assert safe_relative(project_path("data", "serving")).startswith("data/")
