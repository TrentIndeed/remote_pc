"""Configuration for the remote desktop server.

Everything is read from environment variables so nothing sensitive lives in
the repo. The only required variable is RD_PASSWORD.
"""
import os
import secrets


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


class Config:
    # --- network ---
    HOST = os.environ.get("RD_HOST", "127.0.0.1")  # tunnel connects locally
    PORT = _int("RD_PORT", 8080)

    # --- auth ---
    USERNAME = os.environ.get("RD_USERNAME", "admin")
    # Prefer a salted hash (RD_PASSWORD_HASH, "pbkdf2_sha256$iters$salt$hash")
    # so the plaintext never has to live on disk. RD_PASSWORD is still accepted
    # as a fallback for quick local use.
    PASSWORD = os.environ.get("RD_PASSWORD")
    PASSWORD_HASH = os.environ.get("RD_PASSWORD_HASH")
    # Session cookie signing / token entropy. Regenerated each start if unset,
    # which simply means existing sessions don't survive a restart.
    SECRET = os.environ.get("RD_SECRET") or secrets.token_urlsafe(32)
    SESSION_TTL = _int("RD_SESSION_TTL", 8 * 3600)         # seconds (8h; short for a full-control tool)
    MAX_LOGIN_ATTEMPTS = _int("RD_MAX_LOGIN_ATTEMPTS", 8)  # per IP per window
    LOCKOUT_SECONDS = _int("RD_LOCKOUT_SECONDS", 300)
    FAILED_LOGIN_DELAY = _float("RD_FAILED_LOGIN_DELAY", 0.75)  # throttle brute force
    # __Host- prefix pins the cookie to this exact host over HTTPS and forbids
    # a malicious subdomain from overwriting it. Requires Secure + Path=/.
    COOKIE_NAME = os.environ.get("RD_COOKIE_NAME", "__Host-rd_session")
    # CSRF / cross-origin hardening: browser requests must carry an Origin whose
    # host matches the request Host. Extra hostnames can be allowed here (comma
    # separated) if you ever front the app with another name.
    ALLOWED_ORIGINS = [
        h.strip() for h in os.environ.get("RD_ALLOWED_ORIGINS", "").split(",")
        if h.strip()
    ]
    # Trust Cloudflare's CF-Connecting-IP for the real client address (the tunnel
    # itself always connects from 127.0.0.1, which would otherwise collapse all
    # clients into one rate-limit bucket). Safe because only the local tunnel and
    # localhost can reach the 127.0.0.1 listener.
    TRUST_CF_HEADER = os.environ.get("RD_TRUST_CF_HEADER", "1") != "0"

    # --- video ---
    JPEG_QUALITY = _int("RD_JPEG_QUALITY", 70)     # 1-100
    TARGET_FPS = _int("RD_TARGET_FPS", 15)         # cap; static screens send less
    # Frames whose downsampled signature is unchanged are skipped (saves
    # bandwidth while watching a mostly-static pipeline). A keepalive frame is
    # still sent every KEEPALIVE_SECONDS.
    KEEPALIVE_SECONDS = _float("RD_KEEPALIVE_SECONDS", 1.0)

    def validate(self):
        if not (self.PASSWORD or self.PASSWORD_HASH):
            raise SystemExit(
                "No password configured.\n"
                "Set RD_PASSWORD_HASH (preferred) or RD_PASSWORD before starting.\n"
                "On Windows, run .\\run.cmd which generates the hash for you.\n"
            )


config = Config()
