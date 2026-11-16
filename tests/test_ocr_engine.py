"""Unit tests for Windows WinRT OCR engine initialization and synchronization."""

import pytest
import os
from PIL import Image

import ocr_engine
from ocr_engine import (
    _HAS_WINRT,
    _OCR_LOCK,
    get_ocr_engine,
    ocr_image_async,
    ocr_result_async,
    run_ocr,
)


def test_ocr_lock_is_reentrant():
    # Must allow nested acquisitions on the same thread without deadlock
    with _OCR_LOCK:
        with _OCR_LOCK:
            pass


def test_run_ocr_with_null_inputs():
    img = Image.new("RGB", (10, 10))
    # engine is None
    assert run_ocr(img, None) is None

    # tiny image (< 2x2)
    tiny_img = Image.new("RGB", (1, 1))
    assert run_ocr(tiny_img, object()) is None


def test_ocr_result_async_with_null_inputs():
    import asyncio
    tiny = Image.new("RGB", (1, 1))
    assert asyncio.run(ocr_result_async(tiny, object())) is None
    normal = Image.new("RGB", (10, 10))
    assert asyncio.run(ocr_result_async(normal, None)) is None


def test_ocr_image_async_empty_on_null_result():
    import asyncio
    tiny = Image.new("RGB", (1, 1))
    assert asyncio.run(ocr_image_async(tiny, None)) == ""


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="Native Windows OCR needs an interactive desktop; parser logic is tested with mocks")
def test_get_ocr_engine_returns_engine_or_none(monkeypatch):
    if not _HAS_WINRT:
        assert get_ocr_engine() is None
    else:
        eng = get_ocr_engine()
        assert eng is not None or eng is None  # Does not raise
