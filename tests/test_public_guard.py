"""Public audit rejects private paths before content reads."""

from public_guard import content_problems, safe_public_path


def test_private_paths_are_denied():
    for path in (".env", "auth.json", "overlay_config.json", "AI_CONTEXT.md",
                 "tests/fixtures/live_match.json", "captures/frame.png",
                 "credentials.py", "sessions/chat.md", "dist/app.exe"):
        assert not safe_public_path(path)
    assert safe_public_path("advisor_source.py")
    assert safe_public_path(".github/workflows/windows.yml")


def test_sensitive_content_is_reported_without_values():
    fake = "gh" + "p_" + "a" * 36
    result = content_problems("example.py", "value = '" + fake + "'")
    assert result == ["possible private content"]
    assert fake not in str(result)
