"""Model-view control and image capture tools."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
import tempfile
from uuid import uuid4
import zlib

from ..comutil import com
from ..constants import SwErrors, SwViews
from ..core.policy import OperationClass
from ..registry import tool
from .guard import require_output_write


_ORIENTATIONS = (
    "front", "back", "left", "right", "top", "bottom",
    "isometric", "trimetric", "dimetric",
)


def _safe_filename_part(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "unknown"


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _bmp_to_png(bmp_path: Path, png_path: Path, width: int, height: int) -> None:
    """Convert an uncompressed Win32 screen bitmap to a dependency-free PNG."""
    data = bmp_path.read_bytes()
    if data[:2] != b"BM":
        raise ValueError("Captured window bitmap has an invalid header.")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    source_width, signed_height = struct.unpack_from("<ii", data, 18)
    bits_per_pixel = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if source_width <= 0 or signed_height == 0 or bits_per_pixel not in {24, 32} or compression != 0:
        raise ValueError("Captured window bitmap format is unsupported.")
    source_height = abs(signed_height)
    bytes_per_pixel = bits_per_pixel // 8
    stride = ((source_width * bytes_per_pixel + 3) // 4) * 4
    top_down = signed_height < 0

    rows = []
    for output_y in range(height):
        source_y = min(source_height - 1, output_y * source_height // height)
        stored_y = source_y if top_down else source_height - 1 - source_y
        row_start = pixel_offset + stored_y * stride
        row = bytearray([0])
        for output_x in range(width):
            source_x = min(source_width - 1, output_x * source_width // width)
            offset = row_start + source_x * bytes_per_pixel
            blue, green, red = data[offset:offset + 3]
            row.extend((red, green, blue))
        rows.append(bytes(row))

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png_path.write_bytes(
        signature
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=6))
        + _png_chunk(b"IEND", b"")
    )


def _capture_window_png(
    hwnd: int, output_path: Path, width: int, height: int,
    screen_box: tuple[int, int, int, int] | None = None,
):
    """Capture only the SolidWorks model-view client window."""
    import ctypes
    import win32con
    import win32gui
    import win32ui

    foreground = None
    root_window = None
    capture_from_screen = False
    if screen_box is not None:
        foreground = win32gui.GetForegroundWindow()
        root_window = win32gui.GetAncestor(hwnd, 2)
        if win32gui.IsIconic(root_window):
            raise RuntimeError("SolidWorks must be visible to capture the graphics viewport.")
        try:
            win32gui.SetForegroundWindow(root_window)
            capture_from_screen = win32gui.GetForegroundWindow() == root_window
        except Exception:
            capture_from_screen = False
    if capture_from_screen:
        left, top, right, bottom = screen_box
        win32gui.UpdateWindow(root_window)
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass
        window_dc_handle = win32gui.GetDC(0)
        source_origin = (left, top)
    else:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        window_dc_handle = win32gui.GetDC(hwnd)
        source_origin = (0, 0)
    source_width = right - left
    source_height = bottom - top
    if source_width <= 0 or source_height <= 0:
        raise RuntimeError("The active model view has no visible client area.")

    source_dc = win32ui.CreateDCFromHandle(window_dc_handle)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, source_width, source_height)
    previous = memory_dc.SelectObject(bitmap)
    try:
        if capture_from_screen:
            memory_dc.BitBlt(
                (0, 0), (source_width, source_height), source_dc, source_origin,
                win32con.SRCCOPY,
            )
        else:
            # PrintWindow asks the OpenGL-backed child window to render itself.
            printed = ctypes.windll.user32.PrintWindow(
                int(hwnd), int(memory_dc.GetSafeHdc()), 2
            )
            if not printed:
                memory_dc.BitBlt(
                    (0, 0), (source_width, source_height), source_dc, (0, 0),
                    win32con.SRCCOPY,
                )
        with tempfile.NamedTemporaryFile(
            suffix=".bmp", dir=output_path.parent, delete=False
        ) as temporary:
            bmp_path = Path(temporary.name)
        try:
            bitmap.SaveBitmapFile(memory_dc, str(bmp_path))
            _bmp_to_png(bmp_path, output_path, width, height)
        finally:
            bmp_path.unlink(missing_ok=True)
    finally:
        memory_dc.SelectObject(previous)
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(0 if capture_from_screen else hwnd, window_dc_handle)
        if capture_from_screen and foreground and foreground != root_window and win32gui.IsWindow(foreground):
            try:
                win32gui.SetForegroundWindow(foreground)
            except Exception:
                pass
    return width, height


def _validate_orientation(sw, orientation: str):
    normalized = str(orientation).casefold()
    if normalized not in _ORIENTATIONS:
        return None, sw._result(
            False,
            f"Unknown orientation '{orientation}'.",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED", "allowed": list(_ORIENTATIONS)},
        )
    return normalized, None


@tool(
    name="set_view",
    description="Set a standard named view on the active document.",
    schema={"type": "object", "properties": {
        "orientation": {"type": "string", "enum": list(_ORIENTATIONS)},
    }, "required": ["orientation"]},
    operation_class=OperationClass.STATEFUL_READ,
)
def set_view(sw, orientation: str) -> dict:
    normalized, error = _validate_orientation(sw, orientation)
    if error:
        return error
    document, document_error = sw.get_active_doc()
    if document_error:
        return document_error
    name, view_id = SwViews.get(normalized)
    try:
        com(document, "ShowNamedView2", name, view_id)
    except Exception as exc:
        return sw._result(False, f"Could not set view: {exc}", SwErrors.swUnknownError)
    return sw._result(True, f"View set to {normalized}.", data={
        "orientation": normalized, "solidworks_view": name,
    })


@tool(
    name="zoom_fit",
    description="Zoom the active model view to fit its geometry.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.STATEFUL_READ,
)
def zoom_fit(sw) -> dict:
    document, error = sw.get_active_doc()
    if error:
        return error
    try:
        com(document, "ViewZoomtofit2")
    except Exception as exc:
        return sw._result(False, f"Could not zoom to fit: {exc}", SwErrors.swUnknownError)
    return sw._result(True, "Active view zoomed to fit.")


@tool(
    name="capture_view",
    description=(
        "Capture the active model viewport as a revision-bound PNG and restore "
        "the original view afterwards. prepare_view=false captures the current view without "
        "activation, view changes or redraw, preserving native edit context. SolidWorks must remain at least partly visible."
    ),
    schema={"type": "object", "properties": {
        "orientation": {"type": "string", "enum": list(_ORIENTATIONS), "default": "isometric"},
        "prepare_view": {"type":"boolean", "default":True},
        "width": {"type": "integer", "minimum": 64, "maximum": 4096, "default": 1920},
        "height": {"type": "integer", "minimum": 64, "maximum": 4096, "default": 1080},
        "output_path": {"type": "string", "description": "Optional new .png path; existing files are never overwritten."},
    }, "required": []},
    operation_class=OperationClass.STATEFUL_READ,
)
def capture_view(
    sw, orientation: str = "isometric", width: int = 1920, height: int = 1080,
    output_path: str | None = None, prepare_view: bool = True,
) -> dict:
    if not isinstance(prepare_view,bool):
        return sw._result(False,"prepare_view must be boolean.",SwErrors.swInvalidInput)
    normalized, validation_error = _validate_orientation(sw, orientation)
    if validation_error:
        return validation_error
    for label, value in (("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or not 64 <= value <= 4096:
            return sw._result(
                False, f"{label} must be an integer from 64 to 4096.",
                SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
            )

    target, target_error = sw.capture_active_document_ref()
    if target_error:
        return target_error
    if output_path:
        path = Path(output_path).expanduser().resolve()
    else:
        policy = getattr(sw, "_path_policy", None)
        if policy is not None and getattr(policy, "output_roots", ()):
            capture_dir = policy.output_roots[0] / "captures"
        else:
            capture_dir = Path(__file__).resolve().parents[2] / "output" / "captures"
        path = capture_dir / (
            f"{_safe_filename_part(target.document_id)}-"
            f"{_safe_filename_part(target.revision_token)}-{normalized}-"
            f"{uuid4().hex[:8]}.png"
        )
    if path.suffix.casefold() != ".png":
        return sw._result(False, "capture_view output must use .png.", SwErrors.swInvalidInput)
    if path.exists():
        return sw._result(False, f"Capture path already exists: {path}", SwErrors.swFileSaveError)
    denied = require_output_write(sw, str(path))
    if denied:
        return denied

    document, document_error = sw.get_active_doc()
    if document_error:
        return document_error
    title = com(document, "GetTitle")
    if prepare_view:
        try:
            import pythoncom
            import win32com.client
            activation_errors = win32com.client.VARIANT(
                pythoncom.VT_BYREF | pythoncom.VT_I4, 0,
            )
            activation_result = com(sw.app, "ActivateDoc3", title, False, 1, activation_errors)
        except Exception as activation_error:
            return sw._result(
                False, f"Could not activate target document for capture: {activation_error}",
                SwErrors.swUnknownError,
            )
        if isinstance(activation_result, tuple):
            activated = activation_result[0]
            activation_error_code = int(activation_result[1]) if len(activation_result) > 1 else 0
        else:
            activated = activation_result
            activation_error_code = int(activation_errors.value)
        if activated is None or activation_error_code:
            return sw._result(
                False,
                f"Target document activation failed with code {activation_error_code}.",
                SwErrors.swUnknownError,
                {"code": "DOCUMENT_ACTIVATION_FAILED", "activation_error": activation_error_code},
            )
    active_after_activation = com(sw.app, "ActiveDoc")
    if com(active_after_activation, "GetTitle") != title:
        return sw._result(
            False, "Activated viewport does not match the target document.",
            SwErrors.swUnknownError, {"code": "WRONG_DOCUMENT"},
        )
    view = com(document, "ActiveView")
    original_orientation = com(view, "Orientation3")
    original_translation = com(view, "Translation3")
    original_scale = com(view, "Scale2")
    restore_warnings = []
    try:
        if prepare_view:
            name, view_id = SwViews.get(normalized)
            com(document, "ShowNamedView2", name, view_id)
            com(document, "ViewZoomtofit2")
            com(document, "GraphicsRedraw2")
        active_view = com(document, "ActiveView")
        try:
            hwnd = com(active_view, "GetViewHWndx64")
        except Exception:
            hwnd = com(active_view, "GetViewHWnd")
        try:
            raw_box = list(com(active_view, "GetVisibleBox"))
            screen_box = tuple(int(value) for value in raw_box[:4]) if len(raw_box) >= 4 else None
        except Exception:
            screen_box = None
        path.parent.mkdir(parents=True, exist_ok=True)
        actual_width, actual_height = _capture_window_png(
            hwnd, path, width, height, screen_box
        )
    except Exception as exc:
        path.unlink(missing_ok=True)
        return sw._result(False, f"Could not capture model view: {exc}", SwErrors.swExportError)
    finally:
        if prepare_view:
            try:
                current_view = com(document, "ActiveView")
                current_view.Orientation3 = original_orientation
                current_view.Translation3 = original_translation
                current_view.Scale2 = original_scale
                com(document, "GraphicsRedraw2")
            except Exception as restore_error:
                restore_warnings.append(f"Could not restore original model view: {restore_error}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return sw._result(True, "Model view captured and original view restored." if prepare_view else
                      "Current model view captured without activation or view changes.", data={
        "artifact": {
            "path": str(path),
            "mime_type": "image/png",
            "size_bytes": path.stat().st_size,
            "sha256": digest,
            "pixel_size": [actual_width, actual_height],
            "document_id": target.document_id,
            "configuration": target.configuration,
            "revision_token": target.revision_token,
            "orientation": normalized if prepare_view else "current",
        },
        "restore_warnings": restore_warnings,
        "capture_requirement": "SolidWorks must be at least partly visible and not minimized.",
    })
