# Home PC Remote Desktop

A small, self-hosted remote desktop for **a machine you own**. It runs directly
on your home PC, captures the screen, and lets you see and control it from any
browser (desktop or phone) over an authenticated HTTPS link. Built for the
concrete goal of remotely using **VS Code** and watching **Chrome** run the
ParameshAI pipeline across a **3-monitor** setup.

No agent, no ESP32, no capture card — the program drives the machine's own
mouse/keyboard and reads its own screen, with a login in front of it.

```
Phone / laptop browser
      │  HTTPS + WSS (port 443)
      ▼
Cloudflare quick tunnel  ──►  this server (localhost:8080)
                                 ├── mss      → capture chosen monitor → JPEG
                                 ├── pynput   → move/click/type on the host
                                 └── FastAPI  → login + WebSocket bridge
```

## What it does

- Live JPEG video of one monitor at a time, drawn to a `<canvas>`.
- **Multi-monitor:** numbered buttons `1 2 3` to switch screens, plus a
  **two-finger horizontal swipe** on mobile. Clicks always land on the right
  physical screen (absolute positioning).
- Full keyboard + mouse from desktop browsers (modifiers, drag, scroll,
  right-click, double-click).
- Mobile: tap = click, long-press = right-click, double-tap = double-click,
  one-finger drag = drag, two-finger vertical swipe = scroll, pinch = zoom.
  On-screen keyboard toggle, sticky modifier keys (Ctrl/Alt/Shift/Win) for
  combos like Ctrl+C, and a toolbar for Esc/Tab/arrows/F-keys/etc.
- Login with session cookie + per-IP rate limiting.
- Bandwidth-friendly: unchanged frames are skipped, frames are ack-paced so a
  slow link never gets flooded, quality/FPS adjustable from the top bar.

## Prerequisites

- Python 3.10+
- `cloudflared` (for the public HTTPS URL) — optional if you only use it on your LAN
- The OS-level permissions below

Install Python deps:

```bash
pip install -r requirements.txt
```

Install cloudflared (Linux x86_64 example):

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
```

(macOS: `brew install cloudflared`. Windows: download the `.exe` from Cloudflare.)

## Run (Windows — one command)

Credentials live in `secrets.local.ps1` (git-ignored; the password is stored as
a salted PBKDF2 hash, never in plaintext). With that in place, just run:

```cmd
run.cmd
```

or from PowerShell: `.\run.ps1`. It picks a free port, starts the hardened
server, opens a Cloudflare tunnel, and prints the public
`https://<random>.trycloudflare.com` URL plus your username. Open it on your
phone or the corporate laptop's browser, sign in, and you're controlling the
home PC. `run.cmd` also auto-creates the virtualenv and installs dependencies on
first run if `.venv` is missing.

To change the username/password, edit `secrets.local.ps1`. Generate a new
password hash with:

```cmd
.venv\Scripts\python.exe -c "import auth; print(auth.hash_password('NEW-PASSWORD'))"
```

and paste the result into `RD_PASSWORD_HASH`.

## Run (Linux/macOS)

```bash
export RD_USERNAME="you"           # optional, default "admin"
export RD_PASSWORD="something-long-and-unguessable"   # required
bash start.sh
```

It prints a `https://<random>.trycloudflare.com` URL. Open it on your phone or
the corporate laptop's browser, sign in, and you're controlling the home PC.

## Permanent URL (named tunnel)

> **Already configured on this machine.** The named tunnel `homepc-remote` is set
> up and `secrets.local.ps1` sets `RD_TUNNEL_NAME=homepc-remote`, so `run.cmd`
> serves a stable URL:
>
> ### → https://learn.dragonoperator.com
>
> Tunnel credentials live in `C:\Users\<you>\.cloudflared\` (keep them secret;
> they're outside the repo). To remove it: `cloudflared tunnel delete homepc-remote`
> and delete the `learn` DNS record in the Cloudflare dashboard.

The rest of this section documents how that was set up (for reference / a new
machine). The quick-tunnel URL changes every run; for a stable address, do this
**one-time** setup after adding a domain to your Cloudflare account:

```cmd
cloudflared tunnel login                          REM authorize in the browser
cloudflared tunnel create homepc                  REM creates a tunnel + creds
cloudflared tunnel route dns homepc remote.yourdomain.com
```

Then set the tunnel name so the launcher uses it instead of a quick tunnel:

```powershell
$env:RD_TUNNEL_NAME = "homepc"   # or add this line to secrets.local.ps1
.\run.ps1
```

`run.ps1` will run the named tunnel; the URL stays `remote.yourdomain.com`
forever. You can then gate it with **Cloudflare Access** for a second auth layer
(e.g. email one-time-PIN or your IdP) — recommended for the two-step
verification you plan to add.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `RD_PASSWORD_HASH` | — | Salted PBKDF2 hash (preferred over `RD_PASSWORD`) |
| `RD_PASSWORD` | — | Plaintext login password (fallback if no hash) |
| `RD_USERNAME` | `admin` | Login username |
| `RD_PORT` | `8080` | Local server port |
| `RD_JPEG_QUALITY` | `70` | 1–100; lower = less bandwidth |
| `RD_TARGET_FPS` | `15` | Max frame rate (static screens send fewer) |
| `RD_SESSION_TTL` | `28800` | Session lifetime, seconds (8h) |
| `RD_SECRET` | random | **Set a stable value to keep sessions valid across restarts.** Sessions are stateless HMAC-signed tokens keyed by this; if it changes, everyone is logged out. `secrets.local.ps1` sets it. |
| `RD_TELEGRAM_TOKEN` | — | Telegram bot token for login notifications (optional) |
| `RD_TELEGRAM_CHAT_ID` | — | Your Telegram chat id (optional) |

> **Login notifications (Telegram):** if both `RD_TELEGRAM_*` are set, you get a
> Telegram message on every successful login (user, IP, time, device) and when an
> IP is locked out after too many failed attempts. Setup: message **@BotFather**
> → `/newbot` → copy the token; message your new bot once; run
> `.venv\Scripts\python.exe get_chat_id.py <TOKEN>` to get your chat id; put both
> in `secrets.local.ps1`; restart.

> **Sessions:** signed tokens that survive server restarts (as long as
> `RD_SECRET` is stable) and last **8 hours** — short, because this tool fully
> controls the machine. Re-login is one tap since "Remember me" pre-fills your
> credentials. "Sign out" (in the ☰ menu) revokes the current session. Override
> the duration with `RD_SESSION_TTL` (seconds) if you want.

## OS notes (important)

The server controls the machine's real input and reads its real screen, so the
OS must allow that:

- **Windows** — works out of the box. Best experience.
- **macOS** — grant the terminal/Python **Screen Recording** and
  **Accessibility** permissions (System Settings → Privacy & Security).
- **Linux** — use an **X11** session. On **Wayland**, `mss` capture and
  `pynput` input injection are restricted by the compositor and generally
  won't work. Log in choosing "Xorg"/"X11" if your desktop offers it.

Multi-monitor offsets (including monitors placed left of / above the primary,
which produce negative coordinates) are read from the OS and handled.

## Using it

- **Switch screens:** tap `1` / `2` / `3` in the top bar, or two-finger swipe
  left/right on mobile.
- **Zoom (mobile):** pinch to zoom into small text; pan with the same gesture;
  tap **Fit** to reset. Taps stay mapped to the correct spot at any zoom level.
- **Type on mobile:** tap the ⌨ button to open the keyboard. For shortcuts,
  toggle Ctrl/Alt/Shift (they stay held), then type the letter or tap a special
  key, then toggle them off.
- **Quality:** use `+ / –` in the top bar. Raise quality for reading code,
  lower it on a weak connection.

## Security

The server controls your real machine, so it's hardened against the obvious
remote attacks:

- **Password never stored in plaintext.** `RD_PASSWORD_HASH` holds a salted
  PBKDF2-SHA256 hash (240k iterations); credentials are compared in constant time
  and the username/password checks always both run (no timing-based enumeration).
- **Brute-force resistant.** Per-IP rate limiting locks an address out after 8
  failed attempts for 5 minutes, and every failed login is delayed ~0.75s. The
  real client IP is taken from Cloudflare's `CF-Connecting-IP` (without it, the
  tunnel would make every visitor look like `127.0.0.1`).
- **CSRF / cross-origin protection.** Login and the WebSocket reject any request
  whose `Origin` doesn't match the served host — this blocks cross-site
  WebSocket hijacking, where a malicious page tries to drive your PC using your
  logged-in session.
- **Hardened session cookie.** `__Host-` prefixed, `HttpOnly`, `Secure`,
  `SameSite=Lax`, `Path=/` — not readable by JavaScript and pinned to the host.
- **Security headers** on every response: a strict Content-Security-Policy,
  `X-Frame-Options: DENY` + `frame-ancestors 'none'` (anti-clickjacking),
  `nosniff`, `no-referrer`, and HSTS.
- The server binds to `127.0.0.1`; the Cloudflare tunnel terminates TLS, so all
  traffic to the browser is HTTPS/WSS, and the listener is never exposed directly.
- Held keys/buttons are auto-released if the browser disconnects, so a dropped
  connection mid-drag won't leave a key "stuck" on the host.

**Recommended next layer (two-step verification):** put **Cloudflare Access** in
front of a named tunnel (see "Permanent URL" above) to require a second factor
(email OTP or your identity provider) before anyone even reaches the login page.

## Troubleshooting

- **Black screen / capture fails on Linux** → you're probably on Wayland; switch
  to an X11 session.
- **Input does nothing on macOS** → missing Accessibility/Screen Recording
  permission for the process running Python.
- **No tunnel URL** → check `tunnel.log`; confirm `cloudflared` is installed and
  on PATH or sitting in this folder.
- **Only one monitor shows up** → some Linux setups report all screens as one
  combined display; arrangement is read from the OS, so check your display
  settings.
- **Laggy / heavy bandwidth** → lower quality and FPS from the top bar.

## Files

```
remote-desktop/
├── server.py        FastAPI app: auth routes + WebSocket video/input bridge
├── capture.py       mss screen capture + JPEG encode + monitor enumeration
├── controller.py    pynput mouse/keyboard control (absolute positioning)
├── keymap.py        browser KeyboardEvent.code → pynput keys
├── auth.py          sessions + login rate limiting
├── config.py        environment configuration
├── static/
│   └── index.html   single-file UI (login + remote desktop, desktop + mobile)
├── requirements.txt
├── start.sh         launch server + Cloudflare tunnel
└── README.md
```
