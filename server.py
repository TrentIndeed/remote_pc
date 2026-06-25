"""Remote desktop server.

Runs ON the machine being controlled. Serves a single-page UI, authenticates
the operator, then over one WebSocket:
  - streams JPEG frames of the chosen monitor (server -> browser, binary)
  - receives mouse/keyboard input and monitor-switch commands (browser -> server)

Frame flow is ack-paced: the server sends a frame, the browser draws it and
replies {"t":"ack"}, then the next frame is produced. This adapts to the
network automatically and never floods a slow link. Unchanged frames are
skipped (with a periodic keepalive) to save bandwidth on a static screen.
"""
import os
import sys
import time
import json
import asyncio
import threading
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse, Response

from config import config
import auth
import notify
from capture import ScreenCapturer, WebcamSource
from controller import InputController

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    )
    if request.url.path == "/" or request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _client_ip(request_or_ws):
    # Behind the Cloudflare tunnel every request arrives from 127.0.0.1, so use
    # the real client address Cloudflare forwards. Only the local tunnel/loopback
    # can reach this listener, so the header can't be spoofed by a remote attacker.
    if config.TRUST_CF_HEADER:
        cf = request_or_ws.headers.get("cf-connecting-ip")
        if cf:
            return cf.split(",")[0].strip()
    client = request_or_ws.client
    return client.host if client else "unknown"


def _origin_allowed(request_or_ws) -> bool:
    """Block cross-site requests (CSRF + cross-origin WebSocket hijacking).

    Browsers always send Origin on cross-origin POST/WS, so requiring the Origin
    host to equal this request's Host (or an explicit allowlist entry) stops a
    malicious page from driving the host with the victim's session cookie.
    Requests with no Origin (curl, native clients) are allowed -- they can't
    carry the victim's cookie cross-site anyway.
    """
    origin = request_or_ws.headers.get("origin")
    if not origin:
        return True
    try:
        o_host = urlparse(origin).netloc.lower()
    except Exception:
        return False
    if not o_host:
        return False
    host = (request_or_ws.headers.get("host") or "").lower()
    allowed = {host} | {h.lower() for h in config.ALLOWED_ORIGINS}
    return o_host in allowed


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/me")
async def me(request: Request):
    token = request.cookies.get(config.COOKIE_NAME)
    return {"authed": auth.validate_token(token), "username": config.USERNAME}


@app.post("/api/login")
async def login(request: Request):
    if not _origin_allowed(request):
        return JSONResponse({"error": "Bad origin"}, status_code=403)
    ip = _client_ip(request)
    if auth.is_locked(ip):
        return JSONResponse(
            {"error": "Too many attempts. Try again later."}, status_code=429
        )
    try:
        body = await request.json()
    except Exception:
        body = {}
    ua = request.headers.get("user-agent", "?")
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    if auth.check_credentials(body.get("username", ""), body.get("password", "")):
        auth.clear_failures(ip)
        token = auth.create_session()
        notify.send("✅ Remote desktop login\nUser: %s\nIP: %s\nTime: %s\nDevice: %s"
                    % (config.USERNAME, ip, when, ua))
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            config.COOKIE_NAME, token,
            httponly=True, samesite="lax", secure=True,
            max_age=config.SESSION_TTL, path="/",
        )
        return resp
    auth.record_failure(ip)
    if auth.is_locked(ip):   # this failure just crossed the lockout threshold
        notify.send("\U0001f6ab Remote desktop: too many failed logins — IP locked out\nIP: %s\nTime: %s\nDevice: %s"
                    % (ip, when, ua))
    # Slow brute force without blocking the event loop.
    await asyncio.sleep(config.FAILED_LOGIN_DELAY)
    return JSONResponse({"error": "Invalid credentials"}, status_code=401)


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        auth.destroy_session(token)
    resp = JSONResponse({"ok": True})
    # Must mirror the original attributes or the browser won't clear a __Host- cookie.
    resp.delete_cookie(config.COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return resp


# --------------------------------------------------------------------------- #
# Per-connection shared state between the async loop and the capture thread
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self):
        self.monitor = 1
        self.source = "screen"           # "screen" or "webcam"
        self.quality = config.JPEG_QUALITY
        self.fps = config.TARGET_FPS
        self.ready = threading.Event()   # set when the browser can take a frame
        self.stop = threading.Event()
        self.monitor_changed = True      # force a frame_info header on first send
        self.lock = threading.Lock()
        self.monitors = []               # [{index,width,height}] for the UI
        self.geometry = {}               # idx -> {left,top,width,height}

    def fps_interval(self):
        return 1.0 / max(1, self.fps)


def capture_thread(sess: Session, loop, queue: asyncio.Queue):
    """Owns its own mss instance (thread affinity) and produces frames."""
    sc = ScreenCapturer()
    sess.monitors = sc.list_monitors()
    sess.geometry = {i + 1: g for i, g in enumerate(sc.monitors)}

    def push(item):
        loop.call_soon_threadsafe(queue.put_nowait, item)

    # tell the client what's available, right away
    push(("monitors", {"list": sess.monitors, "current": sess.monitor}))

    webcam = WebcamSource(config.WEBCAM_INDEX)

    last_sig = None
    last_send = 0.0
    sent_key = None
    last_cursor = None

    while not sess.stop.is_set():
        if not sess.ready.wait(timeout=0.1):
            continue
        with sess.lock:
            idx = sess.monitor
            source = sess.source
            quality = sess.quality
            interval = sess.fps_interval()
            switched = sess.monitor_changed
            sess.monitor_changed = False

        now = time.time()
        gap = now - last_send
        if gap < interval:
            time.sleep(interval - gap)

        if source == "webcam":
            frame = webcam.grab()
            if frame is None:
                frame = ScreenCapturer.placeholder("Webcam not connected")
            cursor = None
        else:
            try:
                frame = sc.grab(idx)
            except Exception:
                time.sleep(0.1)
                continue
            cursor = sc.cursor_in(idx) if config.SHOW_CURSOR else None

        sig = ScreenCapturer.signature(frame)
        changed = (
            switched
            or sig != last_sig
            or cursor != last_cursor          # send a frame when the cursor moves
            or (time.time() - last_send) > config.KEEPALIVE_SECONDS
        )
        if not changed:
            # leave `ready` set so we re-check promptly when the screen moves
            time.sleep(interval)
            continue

        if cursor is not None:
            frame = ScreenCapturer.draw_cursor(frame, cursor[0], cursor[1])
        jpeg = ScreenCapturer.encode_jpeg(frame, quality)
        last_sig = sig
        last_cursor = cursor
        last_send = time.time()
        sess.ready.clear()

        key = "cam" if source == "webcam" else idx
        if switched or sent_key != key:
            h, w = frame.shape[0], frame.shape[1]
            push(("info", {"mon": key, "w": int(w), "h": int(h)}))
            sent_key = key
        push(("frame", jpeg))

    webcam.release()
    push(("close", None))


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not _origin_allowed(ws):
        await ws.close(code=4403)  # cross-origin WebSocket hijacking attempt
        return
    token = ws.cookies.get(config.COOKIE_NAME)
    if not auth.validate_token(token):
        await ws.close(code=4401)  # unauthorized
        return

    await ws.accept()
    sess = Session()
    sess.ready.set()  # allow the first frame immediately
    ctrl = InputController()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=4)

    thread = threading.Thread(
        target=capture_thread, args=(sess, loop, queue), daemon=True
    )
    thread.start()

    async def sender():
        while True:
            kind, payload = await queue.get()
            if kind == "close":
                break
            elif kind == "frame":
                await ws.send_bytes(payload)
            else:  # text message: monitors / info / pong
                await ws.send_text(json.dumps({"t": kind, **payload}))

    async def receiver():
        while True:
            msg = await ws.receive_text()
            try:
                m = json.loads(msg)
            except Exception:
                continue
            handle_input(m, sess, ctrl)

    def handle_input(m, sess, ctrl):
        t = m.get("t")
        if t == "ack":
            sess.ready.set()
            return
        if t == "ping":
            loop.create_task(_pong(ws, m.get("ts")))
            return
        if t == "mon":
            i = int(m.get("i", 1))
            if 1 <= i <= len(sess.monitors):
                with sess.lock:
                    sess.monitor = i
                    sess.source = "screen"
                    sess.monitor_changed = True
                sess.ready.set()
            return
        if t == "cam":
            with sess.lock:
                sess.source = "webcam"
                sess.monitor_changed = True
            sess.ready.set()
            return
        if t == "q":
            with sess.lock:
                if "jpeg" in m:
                    sess.quality = max(10, min(95, int(m["jpeg"])))
                if "fps" in m:
                    sess.fps = max(1, min(30, int(m["fps"])))
            return

        # the webcam view isn't controllable -- ignore pointer/scroll there
        if sess.source == "webcam" and t in ("m", "d", "u", "dc", "s"):
            return

        # input events use normalized (0..1) coordinates within the current
        # monitor; convert to absolute desktop pixels here.
        if t in ("m", "d", "u", "dc"):
            pos = _to_abs(m, sess)
            if pos is None:
                return
            abs_x, abs_y = pos
            if t == "m":
                ctrl.move(abs_x, abs_y)
            elif t == "d":
                ctrl.button_down(abs_x, abs_y, m.get("b", "left"))
            elif t == "u":
                ctrl.button_up(abs_x, abs_y, m.get("b", "left"))
            elif t == "dc":
                ctrl.double_click(abs_x, abs_y, m.get("b", "left"))
        elif t == "s":
            ctrl.scroll(int(m.get("dx", 0)), int(m.get("dy", 0)))
        elif t == "k":
            ctrl.key(m.get("code", ""), bool(m.get("down")))
        elif t == "type":
            ctrl.type_text(str(m.get("text", "")))

    def _to_abs(m, sess):
        geo = sess.geometry.get(sess.monitor)
        if not geo:
            return None
        nx = min(max(float(m.get("x", 0)), 0.0), 1.0)
        ny = min(max(float(m.get("y", 0)), 0.0), 1.0)
        x = geo["left"] + nx * geo["width"]
        y = geo["top"] + ny * geo["height"]
        return x, y

    async def _pong(ws, ts):
        try:
            await ws.send_text(json.dumps({"t": "pong", "ts": ts}))
        except Exception:
            pass

    try:
        await asyncio.gather(sender(), receiver())
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sess.stop.set()
        ctrl.release_all()  # never leave a key/button stuck


# --------------------------------------------------------------------------- #
# Optional audio: stream the host's system output (WASAPI loopback) as raw PCM
# --------------------------------------------------------------------------- #
@app.websocket("/audio")
async def audio_endpoint(ws: WebSocket):
    if not _origin_allowed(ws):
        await ws.close(code=4403)
        return
    if not auth.validate_token(ws.cookies.get(config.COOKIE_NAME)):
        await ws.close(code=4401)
        return
    await ws.accept()
    rate = config.AUDIO_RATE
    await ws.send_text(json.dumps({"t": "afmt", "rate": rate, "ch": 1}))

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    stop = threading.Event()

    def push(item):
        def _put():
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass  # drop a chunk rather than build latency
        loop.call_soon_threadsafe(_put)

    def capture():
        try:
            import numpy as np
            import soundcard as sc
        except Exception:
            push(None)
            return
        try:
            spk = sc.default_speaker()
            mic = sc.get_microphone(spk.name, include_loopback=True)
            with mic.recorder(samplerate=rate, channels=1,
                              blocksize=config.AUDIO_BLOCK) as rec:
                while not stop.is_set():
                    data = rec.record(numframes=config.AUDIO_BLOCK)  # float32 (n,1)
                    mono = np.clip(data[:, 0], -1.0, 1.0)
                    pcm = (mono * 32767.0).astype("<i2").tobytes()
                    push(pcm)
        except Exception:
            push(None)

    threading.Thread(target=capture, daemon=True).start()
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            await ws.send_bytes(chunk)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    config.validate()
    print("Remote desktop server on http://%s:%d" % (config.HOST, config.PORT))
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
