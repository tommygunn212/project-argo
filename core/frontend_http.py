"""HTTP routes for ARGO's browser frontends.

The handler receives runtime callbacks from main.py so this module never imports
the composition root or creates a second copy of mutable process state.
"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _query_first(query, key, default=None):
    values = query.get(key)
    if not values:
        return default
    return values[0]


def build_frontend_handler(services):
    """Return a request handler bound to the running ARGO process services."""
    repo_root = Path(services["repo_root"])
    http_port = int(services["http_port"])
    ws_port = int(services["ws_port"])

    class FrontendHandler(SimpleHTTPRequestHandler):
        def _send_cors_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
        def _send_json(self, payload, status=200):
            self.send_response(status)
            self.send_header('Content-type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
    
        def _read_json_body(self, max_bytes=65536):
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                return {}
            if length > max_bytes:
                raise ValueError("Request body too large")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    
        def do_OPTIONS(self):
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()
    
        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
    
            if path == "/api/control":
                try:
                    body = self._read_json_body()
                    command = body.get("command") if isinstance(body, dict) else None
                    if not command:
                        self._send_json({"error": "Missing command"}, status=400)
                        return
                    services["handle_control"]({
                        "command": command,
                        "data": body.get("data", {}) if isinstance(body, dict) else {},
                    })
                    self._send_json({"ok": True, "status": services["get_current_status"]()})
                except Exception as exc:
                    services["logger"].exception("[HTTP] control command failed")
                    self._send_json({"error": str(exc)}, status=500)
                return
    
            if path == "/api/hard-stop":
                # Deliberately plain HTTP and local-only: if the websocket is wedged
                # this is the only way left to free ARGO without killing the process.
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    self._send_json({"error": "Forbidden"}, status=403)
                    return
                try:
                    result = services["hard_reset_pipeline"]("HTTP_HARD_STOP")
                    services["set_listening_enabled"](False)
                    services["broadcast_msg"]("status", "IDLE")
                    self._send_json(result)
                except Exception as exc:
                    services["logger"].exception("[HTTP] hard stop failed")
                    self._send_json({"error": str(exc)}, status=500)
                return
    
            if path == "/api/client-log":
                try:
                    body = self._read_json_body()
                    if not isinstance(body, dict):
                        body = {"message": str(body)}
                    allowed_keys = ("phase", "status", "step", "name", "message", "reason", "identity", "room")
                    safe = {
                        key: str(body.get(key, ""))[:500]
                        for key in allowed_keys
                        if key in body
                    }
                    level = str(body.get("level", "info")).lower()
                    line = json.dumps(safe, ensure_ascii=True)
                    if level == "error":
                        services["logger"].error("[CLIENT] %s", line)
                    elif level in ("warn", "warning"):
                        services["logger"].warning("[CLIENT] %s", line)
                    else:
                        services["logger"].info("[CLIENT] %s", line)
                    services["note_smooth_voice_phase"](safe.get("phase", ""))
                    self._send_json({"ok": True})
                except Exception as exc:
                    services["logger"].exception("[HTTP] client log failed")
                    self._send_json({"error": str(exc)}, status=500)
                return
    
            if path == "/api/repair-voice":
                # Local sidecar only; browser origins and unauthenticated calls
                # cannot invoke runtime repairs through this endpoint.
                import secrets
                if (self.client_address[0] not in ("127.0.0.1", "::1")
                        or self.headers.get("Origin") or not services["get_repair_bridge_token"]()
                        or not secrets.compare_digest(self.headers.get("X-Argo-Repair", ""), services["get_repair_bridge_token"]())):
                    self._send_json({"error": "Forbidden"}, status=403)
                    return
                try:
                    body = self._read_json_body(max_bytes=16000)
                    text = str(body.get("text", "")) if isinstance(body, dict) else ""
                    result = services["get_repair_service"]().handle_text(text) if services["get_repair_service"]() else None
                    self._send_json(result or {"status": "error", "message": "Use an ARGO repair request or repair status."})
                except Exception as exc:
                    self._send_json({"status": "error", "message": str(exc)}, status=500)
                return
    
            if path == "/api/vision/analyze-upload":
                try:
                    body = self._read_json_body(max_bytes=10 * 1024 * 1024)
                    if not isinstance(body, dict):
                        self._send_json({"error": "Expected JSON body"}, status=400)
                        return
                    image_data = str(body.get("image_data") or "")
                    prompt = str(body.get("prompt") or "Describe this image for me.").strip()
                    if not prompt:
                        prompt = "Describe this image for me."
                    from tools.vision import analyze_uploaded_image
    
                    answer = analyze_uploaded_image(image_data, user_prompt=prompt[:1000])
                    self._send_json({"ok": True, "answer": answer})
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                except Exception as exc:
                    services["logger"].exception("[VISION] phone image analysis failed")
                    self._send_json({"error": str(exc)}, status=500)
                return
    
            self._send_json({"error": "Not found"}, status=404)
    
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
    
            if path == '/api/status':
                request_host = self.headers.get("Host", f"127.0.0.1:{http_port}").split(":", 1)[0]
                self._send_json({
                    "status": "ok",
                    "service": "ARGO Local Voice Assistant",
                    "ws_endpoint": f"ws://{request_host}:{ws_port}/ws"
                })
            elif path == '/api/livekit-status':
                try:
                    from core.livekit_config import livekit_status
    
                    self._send_json(livekit_status())
                except Exception as exc:
                    services["logger"].exception("[LiveKit] status failed")
                    self._send_json({"error": str(exc)}, status=500)
            elif path == '/api/mobile-access':
                try:
                    from core.livekit_config import mobile_access_status
    
                    request_host = self.headers.get("Host", f"127.0.0.1:{http_port}")
                    self._send_json(mobile_access_status(request_host))
                except Exception as exc:
                    services["logger"].exception("[Mobile] access status failed")
                    self._send_json({"error": str(exc)}, status=500)
            elif path == '/api/home-assistant-status':
                try:
                    from tools.home_assistant import get_connection_status
    
                    self._send_json(get_connection_status())
                except Exception:
                    services["logger"].exception("[Home Assistant] status failed")
                    self._send_json(
                        {"configured": False, "connected": False, "url": ""},
                        status=500,
                    )
            elif path == '/api/livekit-token':
                try:
                    from core.livekit_config import build_livekit_token_response
    
                    payload = build_livekit_token_response(
                        identity=_query_first(query, "identity"),
                        room=_query_first(query, "room"),
                        name=_query_first(query, "name"),
                    )
                    self._send_json(payload)
                except Exception as exc:
                    services["logger"].exception("[LiveKit] token mint failed")
                    self._send_json({"error": str(exc)}, status=500)
            elif path == '/v2/motion-lab':
                # Avatar Motion Lab. Feature-flagged, and deliberately separate
                # from the live avatar: it proves the rig on a neutral placeholder
                # before any of it goes near the final ARGO art.
                if not services["env_enabled"]('ARGO_AVATAR_MOTION_LAB'):
                    self._send_json(
                        {
                            "error": "Motion lab is off",
                            "enable": "set ARGO_AVATAR_MOTION_LAB=1 and restart",
                        },
                        status=404,
                    )
                    return
                lab = repo_root / 'frontend-v2' / 'avatar-motion-lab.html'
                if not lab.exists():
                    self._send_json({"error": "motion lab page missing"}, status=404)
                    return
                content = lab.read_bytes()
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(content)
                return
            elif path.startswith('/v2-assets/'):
                asset_name = Path(path).name
                if asset_name == 'local-avatar-media':
                    try:
                        from core.livekit_config import resolve_local_avatar_media
    
                        asset_path, content_type, _raw_path, error = resolve_local_avatar_media(services["get_config"]())
                    except Exception:
                        services["logger"].exception("[Avatar] local media resolve failed")
                        asset_path, content_type, error = None, "", "error"
                    if error or not asset_path or not asset_path.exists():
                        self.send_response(404)
                        self.send_header('Cache-Control', 'no-store')
                        self._send_cors_headers()
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header('Content-type', content_type)
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(asset_path.read_bytes())
                    return
                allowed_assets = {
                    'livekit-client.umd.js': ('vendor', 'application/javascript; charset=utf-8'),
                    'argo-hedra-default.png': ('assets', 'image/png'),
                    'cortana_portrait_smirky.png': ('assets', 'image/png'),
                    'argo_cyber_male.png': ('assets', 'image/png'),
                    'cortana-avatar.js': ('assets', 'application/javascript; charset=utf-8'),
                    'avatar-motion.js': ('assets', 'application/javascript; charset=utf-8'),
                    'cortana_hedra_avatar_test.mp4': ('assets', 'video/mp4'),
                }
                if asset_name not in allowed_assets:
                    self.send_response(404)
                    self.send_header('Cache-Control', 'no-store')
                    self._send_cors_headers()
                    self.end_headers()
                    return
                asset_dir, content_type = allowed_assets[asset_name]
                asset_path = repo_root / 'frontend-v2' / asset_dir / asset_name
                if not asset_path.exists():
                    self.send_response(404)
                    self.send_header('Cache-Control', 'no-store')
                    self._send_cors_headers()
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(asset_path.read_bytes())
            elif path == '/' or path == '/index.html':
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                try:
                    content = (repo_root / 'frontend' / 'index.html').read_bytes()
                except FileNotFoundError:
                    content = (repo_root / 'index.html').read_bytes()
                self.wfile.write(content)
            elif path in ('/avatar-test', '/cortana-preview'):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.end_headers()
                preview_file = 'cortana-preview.html' if path == '/cortana-preview' else 'avatar-test.html'
                content = (repo_root / 'frontend-v2' / preview_file).read_bytes()
                self.wfile.write(content)
            elif path.startswith('/v2') or path.startswith('/v3'):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.end_headers()
                content = (repo_root / 'frontend-v2' / 'index.html').read_bytes()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass
    

    return FrontendHandler
