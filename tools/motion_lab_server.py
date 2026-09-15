"""Throwaway static server for proving the Avatar Motion Lab.

Deliberately separate from ARGO's own backend so nothing about the running
voice stack has to be restarted or touched to look at the rig.

    python tools\\motion_lab_server.py [port]
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "frontend-v2"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/v2-assets/"):
            return str(WEB / "assets" / Path(clean).name)
        if clean in ("/", "/lab"):
            return str(WEB / "avatar-motion-lab.html")
        return str(WEB / clean.lstrip("/"))

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"  motion lab on http://127.0.0.1:{PORT}/")
        httpd.serve_forever()
