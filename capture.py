"""Screen capture using mss.

mss enumerates monitors as: index 0 == the full virtual desktop (all monitors
combined), then 1..N == each physical monitor with its own left/top offset.
We expose the physical monitors as 1..N and keep their absolute offsets so the
input controller can place the cursor on the correct screen.

NOTE: an mss instance is tied to the thread that created it, so a ScreenCapturer
must be created and used on a single thread (see server.py's capture thread).
"""
import mss
import numpy as np
import cv2


class ScreenCapturer:
    def __init__(self):
        self._sct = mss.mss()
        # drop index 0 (the combined virtual screen)
        self.monitors = list(self._sct.monitors[1:])

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
