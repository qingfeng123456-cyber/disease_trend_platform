from __future__ import annotations

import argparse

from scripts.remote_pipeline import dry_run_plan
from src.remote.config import load_remote_config


def test_remote_pipeline_dry_run_plan_does_not_need_ssh():
    config = load_remote_config("config/remote_cluster.example.yaml", ".env.example")
    args = argparse.Namespace(
        no_start_services=False,
        no_upload_raw=False,
        no_download=False,
        with_yarn=False,
        dry_run=True,
    )
    plan = dry_run_plan(config, "all", args)
    assert plan["remote_project_dir"] == "/home/student/disease_trend_platform"
    assert "sync_project_to_remote" in plan["steps"]
    assert "run_remote_silver_pipeline" in plan["steps"]
    assert "no SSH connection" in plan["note"]
