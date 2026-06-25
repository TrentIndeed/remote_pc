"""Screen capture using mss.

mss enumerates monitors as: index 0 == the full virtual desktop (all monitors
combined), then 1..N == each physical monitor with its own left/top offset.
We expose the physical monitors as 1..N and keep their absolute offsets so the
input controller can place the cursor on the correct screen.

NOTE: an mss instance is tied to the thread that created it, so a ScreenCapturer
must be created and used on a single thread (see server.py's capture thread).
"""
import ctypes
import mss
import numpy as np
import cv2


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_cursor_xy():
    """Global cursor position (x, y), or None off Windows / on failure."""
    if not hasattr(ctypes, "windll"):
        return None
    pt = _POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return (pt.x, pt.y)
    return None


# Classic arrow-pointer outline (relative pixels), drawn at the cursor position.
_CURSOR_PTS = np.array(
    [[0, 0], [0, 18], [4, 14], [7, 21], [10, 20], [7, 13], [13, 13]], np.int32
)


class ScreenCapturer:
    def __init__(self):
        self._sct = mss.mss()
        # drop index 0 (the combined virtual screen)
        self.monitors = list(self._sct.monitors[1:])

    def cursor_in(self, index):
        """Cursor position relative to monitor `index`, or None if off-screen."""
        xy = get_cursor_xy()
        if xy is None:
            return None
        m = self.monitors[index - 1]
        rx, ry = xy[0] - m["left"], xy[1] - m["top"]
        if 0 <= rx < m["width"] and 0 <= ry < m["height"]:
            return (int(rx), int(ry))
        return None

    @staticmethod
    def draw_cursor(bgr, x, y):
        """Draw an arrow pointer (white fill, black outline) at (x, y).

        mss frames are a non-contiguous BGRA->BGR view that cv2 cannot draw onto,
        so make a contiguous copy first. Returns the array to draw/encode.
        """
        if not bgr.flags["C_CONTIGUOUS"]:
            bgr = np.ascontiguousarray(bgr)
        pts = _CURSOR_PTS + (int(x), int(y))
        cv2.fillPoly(bgr, [pts], (255, 255, 255))
        cv2.polylines(bgr, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)
        return bgr

    def list_monitors(self):
        out = []
        for i, m in enumerate(self.monitors, start=1):
            out.append({"index": i, "width": m["width"], "height": m["height"]})
        return out

    def geometry(self, index):
        """Absolute geometry of physical monitor `index` (1-based)."""
        return self.monitors[index - 1]

    def grab(self, index):
        """Return a BGR numpy array for monitor `index` (1-based)."""
        raw = self._sct.grab(self.monitors[index - 1])
        # mss gives BGRA; drop alpha
        return np.asarray(raw)[:, :, :3]

    @staticmethod
    def encode_jpeg(bgr, quality):
        ok, buf = cv2.imencode(
            ".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        )
        if not ok:
            return b""
        return buf.tobytes()

    @staticmethod
    def signature(bgr):
        """Cheap hash of a heavily downsampled frame for change detection."""
        small = bgr[::24, ::24]
        return hash(small.tobytes())

    @staticmethod
    def placeholder(text, w=960, h=540):
        """A simple frame with a centered message (e.g. webcam not connected)."""
        img = np.zeros((h, w, 3), np.uint8)
        img[:] = (28, 24, 20)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        cv2.putText(img, text, ((w - tw) // 2, (h + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2, cv2.LINE_AA)
        return img


import time as _time


class WebcamSource:
    """Lazily-opened webcam. Returns None when no camera is available; callers
    show a placeholder. Retries opening at most every few seconds so a missing
    camera never hammers the capture loop."""

    def __init__(self, index=0, retry_seconds=3.0):
        self.index = index
        self.retry_seconds = retry_seconds
        self.cap = None
        self._next_try = 0.0

    def grab(self):
        if self.cap is None:
            if _time.time() < self._next_try:
                return None
            try:
                cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
            except Exception:
                cap = None
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                self._next_try = _time.time() + self.retry_seconds
                return None
            self.cap = cap
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.release()
            self._next_try = _time.time() + self.retry_seconds
            return None
        return frame

    def release(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
