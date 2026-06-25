# One-command launcher for the Home PC Remote Desktop.
#
#   .\run.cmd          (from cmd or double-click)
#   .\run.ps1          (from PowerShell)
#
# Loads credentials from secrets.local.ps1, starts the hardened server on a free
# port, opens a Cloudflare tunnel (named tunnel if configured, else a quick
# tunnel), and prints the public URL.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- credentials ---------------------------------------------------------- #
$secrets = Join-Path $PSScriptRoot "secrets.local.ps1"
if (Test-Path $secrets) {
    . $secrets
}
if (-not ($env:RD_PASSWORD_HASH -or $env:RD_PASSWORD)) {
    Write-Error "No credentials found. Create secrets.local.ps1 (see README) or set `$env:RD_PASSWORD."
    exit 1
}

# --- pick a free port ----------------------------------------------------- #
function Test-PortFree([int]$p) {
    -not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}
# Default to 8090: port 8080 is used by another service on this machine.
$port = [int]$(if ($env:RD_PORT) { $env:RD_PORT } else { 8090 })
while (-not (Test-PortFree $port)) {
    Write-Host "Port $port is in use, trying $($port + 1) ..."
    $port++
}
$env:RD_PORT = "$port"
$env:RD_HOST = "127.0.0.1"   # localhost only; the tunnel is the only way in

# --- python --------------------------------------------------------------- #
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No venv found; creating one and installing dependencies ..."
    py -m venv .venv
    & (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") -m pip install -q -r requirements.txt
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}

Write-Host "Starting server on 127.0.0.1:$port ..."
$server = Start-Process -FilePath $python -ArgumentList "server.py" -PassThru -NoNewWindow
Start-Sleep -Seconds 2
if ($server.HasExited) {
    Write-Error "Server failed to start (exit $($server.ExitCode)). Check the output above."
    exit 1
}

# --- locate cloudflared --------------------------------------------------- #
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf -and (Test-Path ".\cloudflared.exe")) { $cf = ".\cloudflared.exe" }

if (-not $cf) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1).IPAddress
    Write-Host ""
    Write-Host "cloudflared not found. Reach the server on your LAN at:"
    Write-Host "  http://localhost:$port   (this machine)"
    Write-Host "  http://${ip}:$port       (other devices on your network)"
    try { Wait-Process -Id $server.Id } finally { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
    exit 0
}

# --- start the tunnel ----------------------------------------------------- #
# A named tunnel (stable URL) is used automatically once you've run the one-time
# setup and set $env:RD_TUNNEL_NAME (see README "Permanent URL"). Otherwise a
# quick tunnel with a random URL is used.
if (Test-Path tunnel.log) { Remove-Item tunnel.log -ErrorAction SilentlyContinue }

if ($env:RD_TUNNEL_NAME) {
    Write-Host "Starting named Cloudflare tunnel '$($env:RD_TUNNEL_NAME)' ..."
    $cfArgs = @("tunnel", "run", "--url", "http://localhost:$port", $env:RD_TUNNEL_NAME)
    $named = $true
} else {
    Write-Host "Starting Cloudflare quick tunnel ..."
    $cfArgs = @("tunnel", "--url", "http://localhost:$port")
    $named = $false
}
$tunnel = Start-Process -FilePath $cf -ArgumentList $cfArgs -PassThru -NoNewWindow -RedirectStandardError tunnel.log

# Find the public URL in the log (quick tunnels print a trycloudflare.com URL).
$url = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path tunnel.log) {
        $m = Select-String -Path tunnel.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
    if ($tunnel.HasExited) { break }
}

Write-Host ""
Write-Host "================================================="
Write-Host "  Open this on your phone or any browser:"
if ($url) {
    Write-Host "  $url"
} elseif ($named) {
    Write-Host "  https://<your configured hostname>"
} else {
    Write-Host "  (URL not found yet - check tunnel.log)"
}
Write-Host "  Sign in as: $($env:RD_USERNAME)"
Write-Host "================================================="
Write-Host ""
Write-Host "Press Ctrl+C to stop."

try {
    Wait-Process -Id $server.Id
} finally {
    Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
}
