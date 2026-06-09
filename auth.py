"""Minimal session auth suitable for a single-user, self-hosted tool.

- Constant-time credential comparison.
- Opaque random session tokens stored server-side with a TTL.
- Per-IP login rate limiting / lockout.

This is intentionally simple. The strong protection is your password plus the
TLS that the Cloudflare tunnel terminates. For an extra layer you can also put
Cloudflare Access in front of the tunnel (see README).
"""
import hmac
import time
import base64
import hashlib
import secrets
from collections import defaultdict

from config import config

_attempts = defaultdict(list)       # ip   -> [failure timestamps]


def hash_password(password: str, iterations: int = 240_000) -> str:
    """Produce a "pbkdf2_sha256$iters$salt$hash" string for RD_PASSWORD_HASH."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def _verify_hash(password: str, encoded: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
    except Exception:
        return False
    return hmac.compare_digest(dk, expected)


def check_credentials(username: str, password: str) -> bool:
    # Both checks run unconditionally (the password hash is always computed) so a
    # wrong username and a wrong password cost the same time -- no enumeration.
    user_ok = hmac.compare_digest(username or "", config.USERNAME)
    if config.PASSWORD_HASH:
        pass_ok = _verify_hash(password or "", config.PASSWORD_HASH)
    else:
        pass_ok = hmac.compare_digest(password or "", config.PASSWORD or "")
    return user_ok and pass_ok


def is_locked(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _attempts[ip] if now - t < config.LOCKOUT_SECONDS]
    _attempts[ip] = recent
    return len(recent) >= config.MAX_LOGIN_ATTEMPTS


def record_failure(ip: str) -> None:
    _attempts[ip].append(time.time())


def clear_failures(ip: str) -> None:
    _attempts.pop(ip, None)


# --------------------------------------------------------------------------- #
# Sessions: stateless HMAC-signed tokens.
#
# The token carries its own expiry and is signed with config.SECRET. Because the
# secret is stable across restarts (set in secrets.local.ps1), a logged-in
# browser stays logged in even when the server restarts -- no server-side store
# to lose. Format: "<exp>.<nonce>.<sig>".
# --------------------------------------------------------------------------- #
_revoked = set()  # best-effort logout list (cleared on restart; cookie is also deleted)


def _sign(msg: str) -> str:
    sig = hmac.new(config.SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def create_session() -> str:
    exp = int(time.time() + config.SESSION_TTL)
    payload = "%d.%s" % (exp, secrets.token_urlsafe(8))
    return "%s.%s" % (payload, _sign(payload))


def validate_token(token: str) -> bool:
    if not token or token in _revoked:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    exp_s, nonce, sig = parts
    payload = "%s.%s" % (exp_s, nonce)
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        return time.time() <= int(exp_s)
    except ValueError:
        return False


def destroy_session(token: str) -> None:
    if token:
        _revoked.add(token)
