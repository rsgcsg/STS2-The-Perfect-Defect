from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from sts2_platform_evidence.collection_tool import digest as tool_digest

from stpd.json_boundary import BoundaryError
from stpd.package_identity import file_sha256
from stpd.workbench.collection_tool_registration import (
    REGISTRATION_FILE,
    register_collection_tool,
    registered_collection_tool,
)
from stpd.workbench.developer import ProjectConfig, atomic_json, combination
from stpd.workbench.developer_cli import main
from stpd.workbench.developer_server import instance_lock


def make_tool(directory: Path, marker: str = "first") -> str:
    directory.mkdir()
    for name in ("sts2-human-annotator.dll", "platform-bom.json"):
        (directory / name).write_text(f"synthetic public {marker} {name}")
    identity = {
        "worktree": "clean",
        "source_revision": "a" * 40,
        "workspace_revision": "b" * 40,
        "entrypoint": "sts2-human-annotator.dll",
        "supported_recording_schema": "sts2.human-annotator/recording-manifest-2",
        "files": [
            {"path": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
            for path in sorted(directory.iterdir())
        ],
    }
    release = tool_digest(identity)
    (directory / "collection-tool.json").write_text(
        json.dumps(
            {
                "schema": "sts2.evidence/collection-tool-1",
                "release_id": release,
                "identity": identity,
            }
        )
    )
    return release


@pytest.fixture
def config(tmp_path):
    return ProjectConfig(tmp_path / "state", "", "", None, combination())


def test_registration_is_private_idempotent_and_never_executes(config, tmp_path, monkeypatch):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    assert register_collection_tool(config, directory, release)["changed"] is True
    path = config.state_dir / REGISTRATION_FILE
    before = path.read_bytes()
    assert set(json.loads(before)) == {"schema", "path", "release_id"}
    assert register_collection_tool(config, directory, release)["changed"] is False
    assert path.read_bytes() == before
    assert registered_collection_tool(config, release) == directory.resolve()
    assert calls == []
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("change", ["tamper", "extra", "missing", "wrong_release"])
def test_each_resolution_revalidates_full_public_identity(config, tmp_path, change):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    register_collection_tool(config, directory, release)
    if change == "tamper":
        (directory / "sts2-human-annotator.dll").write_text("changed")
    elif change == "extra":
        (directory / "unlisted.txt").write_text("new untrusted bytes")
    elif change == "missing":
        (directory / "platform-bom.json").unlink()
    else:
        release = "0" * 64
    with pytest.raises(BoundaryError):
        registered_collection_tool(config, release)


def test_conflict_requires_explicit_replace_and_bad_replacement_preserves_pin(config, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first_release = make_tool(first)
    second_release = make_tool(second, "second")
    register_collection_tool(config, first, first_release)
    before = (config.state_dir / REGISTRATION_FILE).read_bytes()
    with pytest.raises(BoundaryError, match="conflict_use_replace_tool"):
        register_collection_tool(config, second, second_release)
    with pytest.raises(BoundaryError, match="identity_verification_failed"):
        register_collection_tool(config, second, first_release, replace=True)
    assert (config.state_dir / REGISTRATION_FILE).read_bytes() == before
    assert register_collection_tool(config, second, second_release, replace=True)["changed"]
    assert registered_collection_tool(config, second_release) == second.resolve()


def test_registration_requires_stopped_workbench(config, tmp_path):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    with (
        instance_lock(config.state_dir / "instance.lock"),
        pytest.raises(BoundaryError, match="already_running"),
    ):
        register_collection_tool(config, directory, release)
    assert not (config.state_dir / REGISTRATION_FILE).exists()


def test_registration_rejects_relative_or_symlink_directory(config, tmp_path):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    with pytest.raises(BoundaryError, match="absolute_non_symlink"):
        register_collection_tool(config, Path("tool"), release)
    link = tmp_path / "tool-link"
    try:
        link.symlink_to(directory, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    with pytest.raises(BoundaryError, match="absolute_non_symlink"):
        register_collection_tool(config, link, release)


def test_registration_file_symlink_is_never_followed_or_replaced(config, tmp_path):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    private = tmp_path / "unrelated-private-file"
    private.write_text("unchanged")
    config.state_dir.mkdir()
    try:
        (config.state_dir / REGISTRATION_FILE).symlink_to(private)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    with pytest.raises(BoundaryError, match="missing_or_unsafe"):
        register_collection_tool(config, directory, release, replace=True)
    with pytest.raises(BoundaryError, match="missing_or_unsafe"):
        registered_collection_tool(config, release)
    assert private.read_text() == "unchanged"


@pytest.mark.skipif(os.name == "nt", reason="Windows privacy follows its local ACL")
def test_registration_file_must_remain_private(config, tmp_path):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    register_collection_tool(config, directory, release)
    (config.state_dir / REGISTRATION_FILE).chmod(0o644)
    with pytest.raises(BoundaryError, match="missing_or_unsafe"):
        registered_collection_tool(config, release)
    register_collection_tool(config, directory, release, replace=True)
    assert registered_collection_tool(config, release) == directory.resolve()


def test_cli_registers_first_tool_without_an_old_delivery_config(config, tmp_path, capsys):
    directory = tmp_path / "tool"
    release = make_tool(directory)
    project = tmp_path / "project.json"
    atomic_json(project, config.to_dict())
    assert (
        main(
            [
                "collection-tool",
                "--config",
                str(project),
                "--tool-directory",
                str(directory),
                "--tool-release-id",
                release,
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "registered"
    assert "path" not in result
    assert registered_collection_tool(config, release) == directory.resolve()
