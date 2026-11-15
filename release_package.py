"""Build a versioned, public-safe Windows archive from explicit inputs."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from version import VERSION
from release_licenses import PYSTRAY_SOURCE_NAME, prepare_sources, write_notices

ROOT = Path(__file__).resolve().parent
PUBLIC_DOCUMENTS = ("README.md", "API_GUIDE.md", "PRIVACY.md", "LICENSE", "THIRD_PARTY_NOTICES.txt")


def package_release(executable: Path, destination: Path, root: Path = ROOT) -> Path:
    """Never walk dist: it may contain the owner's portable settings or logs."""
    inputs = [(executable, "DeadlockWPAOverlay.exe")]
    inputs += [(root / name, name) for name in PUBLIC_DOCUMENTS]
    source = root / "build" / "public_sources" / PYSTRAY_SOURCE_NAME
    if not source.exists():
        source = root / PYSTRAY_SOURCE_NAME
    inputs.append((source, PYSTRAY_SOURCE_NAME))
    for path, _name in inputs:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Required regular release input missing: {path.name}")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"DeadlockWPAOverlay-{VERSION}-windows-x64.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as output:
        for path, name in inputs:
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            output.writestr(entry, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--licenses-ready", action="store_true",
                        help="reuse notices and tray source supplied for a modified-library rebuild")
    parser.add_argument("--exe", type=Path, default=ROOT / "dist" / "release" / "DeadlockWPAOverlay.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "releases")
    args = parser.parse_args(argv)
    if not args.licenses_ready:
        prepare_sources()
        write_notices()
    if not args.skip_build:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "--distpath", str(args.exe.parent), "DeadlockWPAOverlay.spec"],
                       cwd=ROOT, check=True)
    archive = package_release(args.exe, args.output)
    print(f"Release ready: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
