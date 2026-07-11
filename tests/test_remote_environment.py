from __future__ import annotations

from src.remote.remote_environment import RemoteEnvironment


def sample_config():
    return {
        "remote": {
            "project_dir": "/home/student/disease trend platform",
            "conda_env": "disease_platform",
            "conda_executable": "/home/student/miniconda3/bin/conda",
        },
        "bigdata": {
            "java_home": "/opt/java",
            "hadoop_home": "/opt/hadoop",
            "spark_home": "/opt/spark",
            "hadoop_conf_dir": "/opt/hadoop/etc/hadoop",
            "spark_master": "local[*]",
        },
    }


def test_bash_command_quotes_project_path_and_exports_env():
    env = RemoteEnvironment(sample_config())
    command = env.bash_command("python --version")
    assert "bash -lc" in command
    assert "JAVA_HOME" in command
    assert "/home/student/disease trend platform" in command
    assert "\\" not in command


def test_conda_run_does_not_use_conda_activate():
    env = RemoteEnvironment(sample_config())
    command = env.python(["scripts/upload_raw_to_hdfs.py", "--verify"])
    assert "conda activate" not in command
    assert "conda' run -n disease_platform" in command or "conda run -n disease_platform" in command
    assert "scripts/upload_raw_to_hdfs.py" in command


def test_env_prefix_expands_remote_path():
    env = RemoteEnvironment(sample_config())
    prefix = env.env_prefix()
    assert ":$PATH" in prefix
    assert "':$PATH'" not in prefix
