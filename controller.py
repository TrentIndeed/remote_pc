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


class InputController:
    def __init__(self):
        self._mouse = MouseController()
        self._kbd = KeyController()
        self._down_keys = set()
        self._down_buttons = set()

    # --- mouse ---
    def move(self, x, y):
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
