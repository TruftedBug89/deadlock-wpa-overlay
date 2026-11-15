"""Check the public Git tree without reading private or untracked files."""

import argparse
import ast
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parent
BLOCKED_PARTS = {
    ".env", ".agents", ".codex", ".tmp", ".tmp_api", ".venv", "build",
    "captures", "dist", "fixtures", "logs", "sessions", "history",
    "conversations", "__pycache__", ".pytest_cache",
}
BLOCKED_NAMES = {"overlay_config.json", "ai_context.md", "auth.json"}
PUBLIC_SUFFIXES = {".py", ".md", ".txt", ".bat", ".vbs", ".spec", ".lock", ".yml"}
SPECIAL_NAMES = {"LICENSE", ".gitignore", ".gitattributes"}
SECRET_PATTERNS = (
    re.compile(r"(?:github_pat_|gh[pousr]_|sk-proj-)[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api_key|password|access_token)\s*[:=]\s*['\"][A-Za-z0-9/+_=.-]{16,}['\"]"),
    re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!Public\b|user\b|example\b)[A-Za-z0-9_.-]+"),
)


def safe_public_path(name):
    """Reject private paths before attempting to read a byte of their content."""
    path = PurePosixPath(name)
    parts = {part.lower() for part in path.parts}
    if path.is_absolute() or ".." in path.parts or parts & BLOCKED_PARTS:
        return False
    if path.name.lower() in BLOCKED_NAMES:
        return False
    if any(word in path.name.lower() for word in ("credential", "secret", "token", "password")):
        return False
    return path.suffix in PUBLIC_SUFFIXES or path.name in SPECIAL_NAMES


def content_problems(name, text):
    problems = []
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        problems.append("possible private content")
    if "\u2014" in text:
        problems.append("prohibited typography")
    if name.endswith(".py"):
        try:
            ast.parse(text, filename=name)
        except SyntaxError:
            problems.append("invalid Python")
        if not name.startswith("tests/") and len(text.splitlines()) >= 500:
            problems.append("source exceeds line limit")
    return problems


def audit(root=ROOT, staged=False):
    """Inspect only tracked public text; report reasons without offending values."""
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    names = [name for name in names if name]
    if not names:
        return ["No public files are tracked yet."]
    denied = [name for name in names if not safe_public_path(name)]
    if denied:
        return [f"Forbidden public path: {name}" for name in denied]
    modes = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root).decode()
    linked = {entry.split("\t", 1)[1] for entry in modes.split("\0")
              if entry.startswith(("120000", "160000"))}
    blobs = {}
    if staged and not linked:
        request = "\n".join(f":{name}" for name in names) + "\n"
        result = subprocess.run(["git", "cat-file", "--batch"], cwd=root,
                                input=request.encode(), stdout=subprocess.PIPE, check=True)
        cursor = 0
        for name in names:
            end = result.stdout.index(b"\n", cursor)
            size = int(result.stdout[cursor:end].split()[-1])
            blobs[name] = result.stdout[end + 1:end + 1 + size]
            cursor = end + size + 2
    failures = []
    for name in names:
        path = root / name
        if name in linked or path.is_symlink():
            failures.append(f"{name}: symbolic links are not public inputs")
            continue
        data = blobs[name] if staged and not linked else path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            failures.append(f"{name}: non-text input")
            continue
        failures.extend(f"{name}: {issue}" for issue in content_problems(name, text))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    failures = audit(staged=parser.parse_args().staged)
    for failure in failures:
        print(failure)
    if not failures:
        print("Public tree checked: no blocked paths or detected private content.")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
