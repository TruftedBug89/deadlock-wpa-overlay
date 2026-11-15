"""Distribution archives never inherit local settings or nested dist files."""

import hashlib
from zipfile import ZipFile

from release_package import PUBLIC_DOCUMENTS, package_release
from release_licenses import PYSTRAY_SOURCE_NAME


def test_release_has_only_public_inputs(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    dist = root / "dist"
    dist.mkdir()
    executable = dist / "DeadlockWPAOverlay.exe"
    executable.write_bytes(b"synthetic executable")
    (dist / "overlay_config.json").write_text('{"account_id":123}')
    (dist / "run.log").write_text("private test log")
    for name in PUBLIC_DOCUMENTS:
        (root / name).write_text("Public release documentation")
    (root / PYSTRAY_SOURCE_NAME).write_bytes(b"synthetic source archive")
    archive = package_release(executable, dist / "releases", root)
    with ZipFile(archive) as package:
        assert set(package.namelist()) == {"DeadlockWPAOverlay.exe", PYSTRAY_SOURCE_NAME, *PUBLIC_DOCUMENTS}
    checksum = (archive.parent / "SHA256SUMS.txt").read_text()
    assert checksum == f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"


def test_missing_required_document_cannot_create_release(tmp_path):
    import pytest
    executable = tmp_path / "DeadlockWPAOverlay.exe"
    executable.write_bytes(b"synthetic executable")
    with pytest.raises(ValueError, match="Required regular release input missing"):
        package_release(executable, tmp_path / "out", tmp_path)
    assert not (tmp_path / "out").exists()
