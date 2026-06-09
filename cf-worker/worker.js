/**
 * Reverse-proxy Worker for the Home PC remote desktop.
 *
 * Fronts the named Cloudflare tunnel (learn.dragonoperator.com -> this home PC)
 * behind a stable workers.dev URL, passing through HTTP and WebSocket traffic
 * unchanged. The app is served at the root, so no path rewriting is needed.
 *
 * The app's same-origin check must allow this Worker's hostname:
 *   set RD_ALLOWED_ORIGINS=<worker-host> on the server (done in secrets.local.ps1).
 */
const ORIGIN_HOST = "learn.dragonoperator.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.hostname = ORIGIN_HOST;
    url.protocol = "https:";
    url.port = "";
    // new Request(url, request) preserves method, headers (incl. the WebSocket
    // Upgrade handshake), and body; Cloudflare sets Host to the new URL's host.
    return fetch(new Request(url, request));
  },
};
