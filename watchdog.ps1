# Startup watchdog for the Home PC stream.
#
# Run at logon by the Startup-folder launcher. It:
#   1. opens the meshToParametric repo in a new VS Code window, then
#   2. starts the screen-streaming server + Cloudflare named tunnel and keeps
#      them alive with a heartbeat (auto-restarts whatever has died).
#
# The public URL (https://vscode.trentondragon02.workers.dev) is the Cloudflare
# Worker, which proxies to the named tunnel -> this server. The Worker lives in
# the cloud and is always up; this watchdog only has to keep the local server +
# tunnel running.
#
# Modes (optional): -StreamOnly = only manage server+tunnel+heartbeat (used by the
# elevated scheduled task created by apply-hardening.ps1); -AppsOnly = only open
# VS Code + Chrome (non-elevated Startup launcher). Neither = do everything.
param([switch]$StreamOnly, [switch]$AppsOnly)
$ErrorActionPreference = "SilentlyContinue"

$root   = "C:\Users\Trenton\CodeProjects\remote_pc"
$python = Join-Path $root ".venv\Scripts\python.exe"
$cf     = Join-Path $root "cloudflared.exe"
$log    = Join-Path $root "watchdog.log"
$repo   = "C:\Users\Trenton\CodeProjects\meshToParametric"
$codeExe= "C:\Users\Trenton\AppData\Local\Programs\Microsoft VS Code\Code.exe"
$chrome = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

# Operator dashboard digest push: tells the cloud bot what's actually being worked
# on (recent diffs + recent Claude prompts from this repo). Runs at logon + every
# ~2h via the heartbeat loop below.
$opDash    = "C:\Users\Trenton\CodeProjects\operatorDashboard"
$pushDigest= Join-Path $opDash "scripts\push_codebase_digest.py"
$dashApi   = "https://api.dragonoperator.com"
$gitDir    = "C:\Program Files\Git\cmd"

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -Append -Encoding utf8 $log }

# --- credentials / config (RD_PASSWORD_HASH, RD_PORT, RD_TUNNEL_NAME, ...) ---
if (Test-Path "$root\secrets.local.ps1") { . "$root\secrets.local.ps1" }
$port = if ($env:RD_PORT) { [int]$env:RD_PORT } else { 8090 }
$env:RD_PORT = "$port"
$env:RD_HOST = "127.0.0.1"
$tunnel = $env:RD_TUNNEL_NAME

Log "=== watchdog starting (port $port, tunnel '$tunnel') ==="

function Push-Digest {
    # Generate a fresh codebase digest locally and POST it to the dashboard so the
    # VPS bot (which can't see this filesystem) understands current progress. Pure
    # local read + HTTP; no Claude call. Never throws into the watchdog loop.
    if (-not (Test-Path $pushDigest)) { Log "digest push skipped (script missing)"; return }
    if (-not (Test-Path $python))     { Log "digest push skipped (python missing)"; return }
    try {
        if ((Test-Path $gitDir) -and ($env:PATH -notlike "*$gitDir*")) { $env:PATH = "$gitDir;$env:PATH" }
        $env:MESH_REPO_PATH = $repo
        $out = (& $python $pushDigest "--api" $dashApi 2>&1 | Select-Object -First 1)
        Log "digest push: $out"
    } catch { Log "digest push failed: $_" }
}

# --- 1. restore last VS Code session + open Chrome ---
# Launch VS Code with NO folder argument so it reopens the windows that were up
# last time (relies on window.restoreWindows = "all"). If VS Code is already
# running this just focuses it -- it never closes or replaces your open windows.
if (-not $StreamOnly) {
    if (Test-Path $codeExe) { Start-Process $codeExe; Log "launched VS Code (restore last session)" }
    if (Test-Path $chrome) {
        # --restore-last-session reopens the tabs/windows from last time (not a blank window)
        Start-Process $chrome -ArgumentList "--restore-last-session"
        Log "opened Chrome (restore last session)"
    } else { Log "Chrome not found at $chrome" }
}

# --- helpers ---
function Test-Server {
    try { (Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 }
    catch { $false }
}
function Tunnel-Up { [bool](Get-Process cloudflared -ErrorAction SilentlyContinue) }

function Start-Tunnel {
    Start-Process -FilePath $cf -WorkingDirectory $root -WindowStyle Hidden `
        -ArgumentList @("tunnel","run","--url","http://localhost:$port",$tunnel)
}
function Restart-Server {
    # kill whatever holds the port, then start a fresh server. cloudflared keeps
    # pointing at localhost:$port, so the tunnel does NOT need restarting.
    Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -EA SilentlyContinue }
    Start-Sleep 1
    Start-Process -FilePath $python -ArgumentList "server.py" -WorkingDirectory $root -WindowStyle Hidden
}

# --- 2. stream: initial bring-up + heartbeat (skipped in -AppsOnly mode) ---
if (-not $AppsOnly) {
    Restart-Server
    Start-Sleep 3
    if (-not (Tunnel-Up)) { Start-Tunnel }
    Log "stack started (elevated=$([bool]([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)))"

    # Push a digest now that the stream is up (captures last session's work so the
    # morning brief is grounded). Placed after bring-up so a slow API never delays it.
    Push-Digest

    # heartbeat loop: restart only what has died
    $tick = 0
    while ($true) {
        Start-Sleep -Seconds 20
        $tick++
        if (-not (Test-Server)) {
            Log "server DOWN -> restarting server"
            Restart-Server
        }
        elseif (-not (Tunnel-Up)) {
            Log "tunnel DOWN -> restarting tunnel"
            Start-Tunnel
        }
        elseif ($tick % 15 -eq 0) {   # ~ every 5 min when healthy
            Log "heartbeat ok"
        }
        if ($tick % 360 -eq 0) {   # ~ every 2 hours: keep the bot's view of the code fresh
            Push-Digest
        }
    }
}
