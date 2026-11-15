"""Collect public dependency licenses and the exact LGPL tray-library source."""

import hashlib
from importlib.metadata import distribution
from pathlib import Path
import ssl
import sys
import urllib.request


ROOT = Path(__file__).resolve().parent
PYSTRAY_SOURCE_NAME = "pystray-0.19.5-source.tar.gz"
PYSTRAY_COMMIT = "1907f8681d6d421517c63d94f425f9cdd74d0034"
PYSTRAY_SOURCE_URL = (
    "https://codeload.github.com/moses-palmer/pystray/tar.gz/" + PYSTRAY_COMMIT
)
PYSTRAY_SHA256 = "2df980e432f349815c8b1e88f910c085c161a17ce7294f73a0e8d7651c5d9bac"

INTRODUCTION = """THIRD-PARTY NOTICES

This file collects original license texts from the build's installed packages,
Python and Tcl/Tk. Some notices cover build tools or optional binary components.
Their inclusion does not change the license of the overlay's original code.
No dependency source is modified by this application.

The pystray tray library is licensed under LGPL-3.0. Its full, unmodified source
is provided alongside this file as pystray-0.19.5-source.tar.gz. This archive is
from upstream v0.19.5, commit 1907f8681d6d421517c63d94f425f9cdd74d0034.
Source: https://github.com/moses-palmer/pystray/tree/v0.19.5

To modify or replace pystray, obtain the matching public overlay source from
https://github.com/TruftedBug89/deadlock-wpa-overlay and follow README.md to set up
its build environment. Extract the included pystray source, edit it, and install
it into that virtual environment with python -m pip install --no-deps PATH.
Then run python release_package.py --licenses-ready to rebuild the application
with your modified tray library. The build has no signature or integrity lock
preventing such replacements. Retain any notices required for your modifications.

Other upstream sources are available from the package project links on PyPI,
https://github.com/python/cpython, https://github.com/tcltk/tcl,
https://github.com/tcltk/tk and https://github.com/openssl/openssl.

"""


def prepare_sources(root: Path = ROOT) -> Path:
    """Fetch the small pinned source archive, verify it, and never extract it."""
    if distribution("pystray").version != "0.19.5":
        raise ValueError("Update the source archive when changing pystray version")
    path = root / "build" / "public_sources" / PYSTRAY_SOURCE_NAME
    data = path.read_bytes() if path.exists() else None
    if data is None or hashlib.sha256(data).hexdigest() != PYSTRAY_SHA256:
        request = urllib.request.Request(PYSTRAY_SOURCE_URL, headers={"User-Agent": "DeadlockWPAOverlay-build"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000 or hashlib.sha256(data).hexdigest() != PYSTRAY_SHA256:
            raise ValueError("Upstream tray source checksum mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def _section(title, source, text):
    """Use relative license labels so local build paths never enter notices."""
    return f"\n{'=' * 72}\n{title}\nSource: {source}\n{'=' * 72}\n\n{text}\n"


def _package_notices(root):
    sections = []
    for line in (root / "requirements-build.lock").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name = line.split("==", 1)[0]
        package = distribution(name)
        found = []
        for relative in package.files or []:
            label = str(relative).replace("\\", "/")
            if ".dist-info/" not in label:
                continue
            if not Path(label).name.lower().startswith(("license", "copying", "notice")):
                continue
            text = package.locate_file(relative).read_text(encoding="utf-8-sig")
            found.append(_section(f"{package.metadata['Name']} {package.version}", label, text))
        if not found:
            raise ValueError(f"No installed license found for dependency {name}")
        sections.extend(found)
    return sections


def write_notices(root: Path = ROOT) -> Path:
    """Generate notices from explicit library/license inputs only."""
    sections = [INTRODUCTION]
    sections.extend(_package_notices(root))
    python_root = Path(sys.base_prefix)
    python_license = python_root / "LICENSE.txt"
    sections.append(_section(f"Python {sys.version.split()[0]}", "Python/LICENSE.txt",
                             python_license.read_text(encoding="utf-8-sig")))
    tk_license = python_root / "tcl" / "tk8.6" / "license.terms"
    sections.append(_section("Tk", "Tk/license.terms", tk_license.read_text(encoding="utf-8")))
    for name, title, source in (
        ("TCL_LICENSE.txt", "Tcl", "https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms"),
        ("OPENSSL_LICENSE.txt", ssl.OPENSSL_VERSION,
         "https://github.com/openssl/openssl/blob/openssl-3.5.4/LICENSE.txt"),
    ):
        sections.append(_section(title, source, (root / "licenses" / name).read_text(encoding="utf-8")))
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL 3."):
        raise ValueError("Review OpenSSL license when changing major versions")
    result = "\n".join(line.rstrip() for line in "".join(sections).splitlines()).rstrip() + "\n"
    if chr(0x2014) in result:
        raise ValueError("An upstream license contains prohibited punctuation; review before release")
    output = root / "THIRD_PARTY_NOTICES.txt"
    output.write_text(result, encoding="utf-8")
    return output


def main():
    source = prepare_sources()
    notice = write_notices()
    print(f"Prepared {notice.name} and {source.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
