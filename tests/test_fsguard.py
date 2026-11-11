import os

import pytest

from scopehound.fsguard import (
    WorkspaceError,
    check_not_reserved,
    resolve_root,
    safe_target,
)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "hosts.txt").write_text("a\nb\n")
    (root / "sub").mkdir()
    return resolve_root(root)


def test_allows_files_inside(ws):
    assert safe_target(ws, "hosts.txt").name == "hosts.txt"
    assert safe_target(ws, "sub/new.txt", for_write=True).name == "new.txt"


@pytest.mark.parametrize(
    "bad",
    ["../secret", "/etc/passwd", "sub/../../x", "..", ".", "", "a/../../b"],
)
def test_blocks_escape(ws, bad):
    with pytest.raises(WorkspaceError):
        safe_target(ws, bad)


def test_blocks_symlink_read(ws, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("segredo")
    os.symlink(outside, ws / "link.txt")
    with pytest.raises(WorkspaceError):
        safe_target(ws, "link.txt")


def test_blocks_symlinked_parent_on_write(ws, tmp_path):
    outside_dir = tmp_path / "out"
    outside_dir.mkdir()
    os.symlink(outside_dir, ws / "escape")
    with pytest.raises(WorkspaceError):
        safe_target(ws, "escape/evil.txt", for_write=True)


def test_reserved_dir_rejected(ws, tmp_path):
    check_not_reserved(ws, [tmp_path / "other"])  # ok
    with pytest.raises(WorkspaceError):
        check_not_reserved(ws, [ws])  # igual
    with pytest.raises(WorkspaceError):
        check_not_reserved(ws, [ws.parent])  # workspace dentro da reservada
    with pytest.raises(WorkspaceError):
        check_not_reserved(ws, [ws / "sub"])  # reservada dentro do workspace
