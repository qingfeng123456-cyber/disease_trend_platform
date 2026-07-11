from __future__ import annotations

from src.remote.cluster_manager import parse_jps


def test_parse_jps_detects_hdfs_and_yarn_processes():
    output = """1234 NameNode
2345 DataNode
3456 SecondaryNameNode
4567 ResourceManager
5678 NodeManager
"""
    processes = parse_jps(output)
    assert "NameNode" in processes
    assert "DataNode" in processes
    assert "ResourceManager" in processes
    assert "NodeManager" in processes


def test_parse_jps_empty_output_is_safe():
    assert parse_jps("") == set()
