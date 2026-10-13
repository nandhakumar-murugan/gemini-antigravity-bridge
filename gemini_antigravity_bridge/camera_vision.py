"""
Gemini Antigravity Bridge & Live Companion — Camera Vision Engine
Provides:
  - Real-time laptop webcam streaming via OpenCV DirectShow
  - Single-shot camera capture & base64 encoding for MCP tools
  - Picture-in-Picture (PiP) compositing for Gemini Live Desktop Companion
  - User activity/reels detection snapshots
"""

import os
import cv2
import time
import base64
import threading
from io import BytesIO
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image, ImageDraw


class CameraManager:
    """Singleton background camera reader that manages the webcam cleanly and thread-safely."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CameraManager, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.device_index = 0
        self.is_streaming = False
        self.latest_frame: Optional[Image.Image] = None
        self.thread: Optional[threading.Thread] = None
        self.frame_lock = threading.Lock()
        self.last_access = 0.0

    def start_stream(self, device_index: int = 0, width: int = 640, height: int = 480):
        with self.frame_lock:
            if self.is_streaming and self.cap and self.cap.isOpened():
                return
            self.device_index = device_index
            self.cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(device_index)

            if not self.cap.isOpened():
                print(f"[WARN] Failed to open laptop camera {device_index}")
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.is_streaming = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            print("[CAMERA] Laptop camera streaming active.")

    def _worker(self):
        # Warm up exposure
        for _ in range(3):
            if self.cap:
                self.cap.grab()

        while self.is_streaming and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                with self.frame_lock:
                    self.latest_frame = img
            time.sleep(0.03)  # ~30 FPS internal capture

    def get_frame(self) -> Optional[Image.Image]:
        self.last_access = time.time()
        with self.frame_lock:
            if self.latest_frame:
                return self.latest_frame.copy()

        # Fallback: single shot if not streaming
        return self.capture_single_frame()

    def capture_single_frame(self, device_index: int = 0, width: int = 640, height: int = 480) -> Optional[Image.Image]:
        with self.frame_lock:
            if self.is_streaming and self.latest_frame:
                return self.latest_frame.copy()

            cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(device_index)

            if not cap.isOpened():
                return None

            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                for _ in range(3):
                    cap.grab()
                ret, frame = cap.read()
                if not ret or frame is None:
                    return None
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return Image.fromarray(rgb)
            finally:
                cap.release()

    def stop_stream(self):
        with self.frame_lock:
            self.is_streaming = False
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.latest_frame = None
            print("[CAMERA] Laptop camera released.")


_camera_mgr = CameraManager()


def capture_camera_photo(save_to_desktop: bool = False, prompt_context: str = "") -> dict:
    """
    Captures a high-resolution snapshot from laptop camera.
    Returns status, resolution, timestamp, local file path, and base64 preview.
    """
    img = _camera_mgr.get_frame()
    if img is None:
        return {"status": "error", "error": "Unable to access laptop camera. Check if privacy shutter or another app holds the webcam."}

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    w, h = img.size

    # Target directory
    root_dir = os.path.dirname(os.path.abspath(__file__))
    captures_dir = os.path.join(root_dir, "scratch", "camera_captures")
    os.makedirs(captures_dir, exist_ok=True)

    filename = f"camera_{timestamp_str}.jpg"
    file_path = os.path.join(captures_dir, filename)
    img.save(file_path, "JPEG", quality=85)

    desktop_path = None
    if save_to_desktop:
        try:
            user_desktop = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\smnk2"), "Desktop")
            if os.path.exists(user_desktop):
                desktop_file = os.path.join(user_desktop, f"Laptop_Camera_Snapshot_{timestamp_str}.jpg")
                img.save(desktop_file, "JPEG", quality=90)
                desktop_path = desktop_file
        except Exception as e:
            print(f"[WARN] Failed to save copy to desktop: {e}")

    # Base64 encoding
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64_full = base64.b64encode(buf.getvalue()).decode("utf-8")

    return {
        "status": "ok",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "resolution": f"{w}x{h}",
        "file_path": file_path,
        "desktop_file": desktop_path,
        "base64_preview": f"data:image/jpeg;base64,{b64_full[:60]}...",
        "base64_full": b64_full,
        "size_bytes": len(buf.getvalue()),
        "prompt_context": prompt_context
    }


def overlay_camera_pip(
    screen_img: Image.Image,
    camera_img: Optional[Image.Image] = None,
    pip_scale: float = 0.22,
    position: str = "bottom-right",
    margin: int = 16,
    border_width: int = 3,
    border_color: Tuple[int, int, int] = (16, 185, 129),  # Emerald green
) -> Image.Image:
    """
    Overlays webcam thumbnail onto the desktop screen capture.
    Allows Gemini Live to watch BOTH the desktop screen AND the user via webcam in 1 video feed!
    """
    if camera_img is None:
        camera_img = _camera_mgr.get_frame()

    if camera_img is None:
        return screen_img

    try:
        canvas = screen_img.copy()
        sw, sh = canvas.size

        # Compute PiP dimensions
        pip_w = int(sw * pip_scale)
        cw, ch = camera_img.size
        aspect = ch / cw if cw > 0 else 0.75
        pip_h = int(pip_w * aspect)

        # Resize camera thumbnail
        thumb = camera_img.resize((pip_w, pip_h), Image.Resampling.BILINEAR)

        # Placement
        if position == "bottom-right":
            x = sw - pip_w - margin
            y = sh - pip_h - margin
        elif position == "top-right":
            x = sw - pip_w - margin
            y = margin
        elif position == "bottom-left":
            x = margin
            y = sh - pip_h - margin
        else: # top-left
            x = margin
            y = margin

        # Draw clean border around PiP box
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            [x - border_width, y - border_width, x + pip_w + border_width - 1, y + pip_h + border_width - 1],
            fill=border_color
        )

        # Paste webcam
        canvas.paste(thumb, (x, y))
        return canvas
    except Exception as e:
        print(f"[WARN in overlay_camera_pip]: {e}")
        return screen_img
