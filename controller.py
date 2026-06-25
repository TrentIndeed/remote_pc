"""Drive the host's real mouse and keyboard via pynput.

All mouse positioning is absolute across the virtual desktop, so a click on
monitor 2 lands on monitor 2 regardless of where the cursor was.

Held keys and buttons are tracked so they can all be released if the browser
disconnects mid-drag or with a modifier held (prevents "stuck Ctrl").
"""
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyController

import keymap

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


# --------------------------------------------------------------------------- #
# Absolute mouse move via SendInput (Windows).
#
# pynput moves with SetCursorPos, which repositions the cursor but does NOT
# inject a real mouse-move into the input stream -- so hover effects (taskbar
# thumbnail previews, tooltips, :hover states) don't fire. SendInput with
# MOUSEEVENTF_MOVE simulates hardware movement and triggers them properly.
# --------------------------------------------------------------------------- #
try:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _SM = {"x": 76, "y": 77, "cx": 78, "cy": 79}  # SM_*VIRTUALSCREEN
    _MOVE, _ABS, _VDESK = 0x0001, 0x8000, 0x4000

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def _send_move_abs(x, y):
        vx = _user32.GetSystemMetrics(_SM["x"])
        vy = _user32.GetSystemMetrics(_SM["y"])
        vw = _user32.GetSystemMetrics(_SM["cx"]) or 1
        vh = _user32.GetSystemMetrics(_SM["cy"]) or 1
        nx = int((int(x) - vx) * 65535 / max(1, vw - 1))
        ny = int((int(y) - vy) * 65535 / max(1, vh - 1))
        mi = _MOUSEINPUT(nx, ny, 0, _MOVE | _ABS | _VDESK, 0, None)
        inp = _INPUT(type=0, mi=mi)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
except Exception:
    _send_move_abs = None


class InputController:
    def __init__(self):
        self._mouse = MouseController()
        self._kbd = KeyController()
        self._down_keys = set()
        self._down_buttons = set()

    # --- mouse ---
    def move(self, x, y):
        # SendInput so hover effects (taskbar thumbnails, tooltips) fire; fall
        # back to pynput's SetCursorPos if SendInput isn't available.
        if _send_move_abs is not None:
            try:
                _send_move_abs(x, y)
                return
            except Exception:
                pass
        self._mouse.position = (int(x), int(y))

    def button_down(self, x, y, button="left"):
        self.move(x, y)
        b = _BUTTONS.get(button, Button.left)
        self._mouse.press(b)
        self._down_buttons.add(b)

    def button_up(self, x, y, button="left"):
        self.move(x, y)
        b = _BUTTONS.get(button, Button.left)
        self._mouse.release(b)
        self._down_buttons.discard(b)

    def double_click(self, x, y, button="left"):
        self.move(x, y)
        self._mouse.click(_BUTTONS.get(button, Button.left), 2)

    def scroll(self, dx, dy):
        # Browser wheel deltaY is positive when scrolling down; pynput scroll
        # is positive when scrolling up -> invert dy.
        self._mouse.scroll(int(dx), -int(dy))

    # --- keyboard ---
    def key(self, code, down):
        k = keymap.resolve(code)
        if k is None:
            return
        if down:
            self._kbd.press(k)
            self._down_keys.add(k)
        else:
            self._kbd.release(k)
            self._down_keys.discard(k)

    def type_text(self, text):
        if text:
            self._kbd.type(text)

    # --- safety ---
    def release_all(self):
        for k in list(self._down_keys):
            try:
                self._kbd.release(k)
            except Exception:
                pass
        self._down_keys.clear()
        for b in list(self._down_buttons):
            try:
                self._mouse.release(b)
            except Exception:
                pass
        self._down_buttons.clear()
