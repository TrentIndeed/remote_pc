"""Optional push notifications for login events.

Currently supports Telegram. Fire-and-forget (runs in a background thread) so a
slow/unreachable notifier never delays or breaks the login response. A no-op if
nothing is configured.
"""
import threading
import urllib.parse
import urllib.request

from config import config


def _post(url, data):
    try:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def send(text):
    """Send `text` to every configured channel, without blocking the caller."""
    if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
        url = "https://api.telegram.org/bot%s/sendMessage" % config.TELEGRAM_TOKEN
        threading.Thread(
            target=_post,
            args=(url, {"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                        "disable_web_page_preview": "true"}),
            daemon=True,
        ).start()
