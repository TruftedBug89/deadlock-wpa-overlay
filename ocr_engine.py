"""Windows WinRT OCR engine management and image recognition primitives."""

import asyncio
import ctypes
import io
import threading
from typing import Optional

from PIL import Image

try:  # Windows 10/11 built-in OCR
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    _HAS_WINRT = True
except (ImportError, OSError, Exception) as err:  # pragma: no cover - depends on host
    print(f"[OCR] WinRT import error: {err}")
    _HAS_WINRT = False

_OCR_ENGINE: Optional[object] = None
_OCR_LOCK = threading.RLock()
_OCR_INIT_LOCK = threading.Lock()


def get_ocr_engine() -> Optional[object]:
    """Create the Windows OCR engine once per process."""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if not _HAS_WINRT:
        return None
    with _OCR_INIT_LOCK:
        if _OCR_ENGINE is not None:
            return _OCR_ENGINE
        try:
            from win32_overlay import attach_to_default_desktop

            attach_to_default_desktop()
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        except Exception:
            pass
        try:
            _OCR_ENGINE = OcrEngine.try_create_from_user_profile_languages()
        except Exception:
            _OCR_ENGINE = None
        return _OCR_ENGINE


async def ocr_result_async(pil_img: Image.Image, engine, upscale: float = 1.0):
    """Execute Windows OCR asynchronously on a PIL image."""
    if pil_img.width < 2 or pil_img.height < 2 or engine is None:
        return None
    try:
        if upscale and upscale != 1.0:
            pil_img = pil_img.resize(
                (max(2, int(pil_img.width * upscale)), max(2, int(pil_img.height * upscale))),
                Image.Resampling.LANCZOS,
            )
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(buffer.getvalue())
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        return await engine.recognize_async(bitmap)
    except Exception:
        return None


def run_ocr(pil_img: Image.Image, engine, upscale: float = 1.0) -> Optional[object]:
    """Execute Windows OCR with exclusive thread serialization."""
    if engine is None or pil_img.width < 2 or pil_img.height < 2:
        return None
    with _OCR_LOCK:
        try:
            return asyncio.run(ocr_result_async(pil_img, engine, upscale))
        except Exception:
            return None


async def ocr_image_async(pil_img: Image.Image, engine, upscale: float = 2.5) -> str:
    """OCR one PIL image in memory using Windows.Media.Ocr."""
    res = await ocr_result_async(pil_img, engine, upscale)
    return (res.text or "").strip() if res else ""


# Compatibility aliases for underscore prefix callers
_get_ocr_engine = get_ocr_engine
_ocr_result_async = ocr_result_async
_run_ocr = run_ocr
_ocr_image_async = ocr_image_async
