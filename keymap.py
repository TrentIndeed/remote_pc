"""Translate browser ``KeyboardEvent.code`` values into pynput keys.

Letters / digits / punctuation resolve to their *unshifted* base character.
Shift (and other modifiers) are tracked separately by the browser and pressed
on the host independently, exactly like a physical keyboard -- so holding Shift
and pressing ``KeyA`` produces "A", and Shift + ``Digit1`` produces "!".
"""
from pynput.keyboard import Key

# code -> pynput.Key for non-character keys
SPECIAL = {
    "Enter": Key.enter, "NumpadEnter": Key.enter,
    "Tab": Key.tab, "Escape": Key.esc,
    "Backspace": Key.backspace, "Delete": Key.delete, "Insert": Key.insert,
    "Space": Key.space,
    "ArrowUp": Key.up, "ArrowDown": Key.down,
    "ArrowLeft": Key.left, "ArrowRight": Key.right,
    "Home": Key.home, "End": Key.end,
    "PageUp": Key.page_up, "PageDown": Key.page_down,
    "CapsLock": Key.caps_lock,
    "ShiftLeft": Key.shift, "ShiftRight": Key.shift_r,
    "ControlLeft": Key.ctrl, "ControlRight": Key.ctrl_r,
    "AltLeft": Key.alt, "AltRight": Key.alt_r,
    "MetaLeft": Key.cmd, "MetaRight": Key.cmd_r,
    "ContextMenu": Key.menu,
    "PrintScreen": Key.print_screen,
    "ScrollLock": Key.scroll_lock,
    "Pause": Key.pause,
}

# F1..F12
for _i in range(1, 13):
    SPECIAL["F%d" % _i] = getattr(Key, "f%d" % _i)

# code -> unshifted character
CHAR = {
    "Minus": "-", "Equal": "=",
    "BracketLeft": "[", "BracketRight": "]", "Backslash": "\\",
    "Semicolon": ";", "Quote": "'", "Backquote": "`",
    "Comma": ",", "Period": ".", "Slash": "/",
    "NumpadDecimal": ".", "NumpadAdd": "+", "NumpadSubtract": "-",
    "NumpadMultiply": "*", "NumpadDivide": "/",
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    CHAR["Key" + _c] = _c.lower()
for _d in "0123456789":
    CHAR["Digit" + _d] = _d
    CHAR["Numpad" + _d] = _d


def resolve(code):
    """Return a pynput Key, a single-character str, or None if unknown."""
    if code in SPECIAL:
        return SPECIAL[code]
    return CHAR.get(code)
