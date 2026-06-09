# Start the remote desktop server on Windows, optionally exposing it over a
# Cloudflare tunnel. Run from this directory:  .\start.ps1
#
# Requires RD_PASSWORD to be set, e.g.:
#   $env:RD_PASSWORD = "something-long-and-unguessable"
#   .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not $env:RD_PASSWORD) {
    Write-Error "Set RD_PASSWORD first, e.g.  `$env:RD_PASSWORD = 'your-strong-password'"
    exit 1
}

function Test-PortFree([int]$p) {
    -not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

# Pick a port: honor RD_PORT, otherwise 8080. If busy, walk forward to a free one.
$port = [int]$(if ($env:RD_PORT) { $env:RD_PORT } else { 8080 })
while (-not (Test-PortFree $port)) {
    Write-Host "Port $port is in use, trying $($port + 1) ..."
    $port++
}
$env:RD_PORT = "$port"
$env:RD_HOST = "127.0.0.1"   # server listens on localhost only; the tunnel is the way in

# Prefer the project venv's Python, fall back to system Python.
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "Starting server on 127.0.0.1:$port ..."
$server = Start-Process -FilePath $python -ArgumentList "server.py" -PassThru -NoNewWindow
Start-Sleep -Seconds 2

# Locate cloudflared (on PATH or ./cloudflared.exe)
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
    Wait-Process -Id $server.Id
} else {
    Write-Host "Starting Cloudflare tunnel ..."
    if (Test-Path tunnel.log) { Remove-Item tunnel.log }
    $tunnel = Start-Process -FilePath $cf `
        -ArgumentList "tunnel", "--url", "http://localhost:$port" `
        -PassThru -NoNewWindow -RedirectStandardError tunnel.log
    # Wait for the public URL to appear in the log.
    $url = $null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path tunnel.log) {
            $m = Select-String -Path tunnel.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $url = $m.Matches[0].Value; break }
        }
    }
    Write-Host ""
    Write-Host "================================================="
    Write-Host "  Open this on your phone or any browser:"
    if ($url) { Write-Host "  $url" } else { Write-Host "  (URL not found yet - check tunnel.log)" }
    Write-Host "================================================="
    Write-Host ""
    try {
        Wait-Process -Id $server.Id
    } finally {
        Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
    }
}
