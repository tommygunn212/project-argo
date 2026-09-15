"""Serve the Avatar Motion Lab behind a feature flag.

Off unless ARGO_AVATAR_MOTION_LAB is set. Nothing in the Smooth Voice audio
path is touched: the lab is a separate page that reads an audio file or a
synthetic signal, and the motion engine is a standalone asset.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "main.py"

OLD_ASSET = """                'cortana-avatar.js': ('assets', 'application/javascript; charset=utf-8'),
"""
NEW_ASSET = """                'cortana-avatar.js': ('assets', 'application/javascript; charset=utf-8'),
                'avatar-motion.js': ('assets', 'application/javascript; charset=utf-8'),
"""

OLD_ROUTE = """        elif path.startswith('/v2-assets/'):
"""
NEW_ROUTE = """        elif path == '/v2/motion-lab':
            # Avatar Motion Lab. Feature-flagged, and deliberately separate
            # from the live avatar: it proves the rig on a neutral placeholder
            # before any of it goes near the final ARGO art.
            if not _env_enabled('ARGO_AVATAR_MOTION_LAB'):
                self._send_json(
                    {
                        "error": "Motion lab is off",
                        "enable": "set ARGO_AVATAR_MOTION_LAB=1 and restart",
                    },
                    status=404,
                )
                return
            lab = Path(__file__).parent / 'frontend-v2' / 'avatar-motion-lab.html'
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
"""

HELPER = '''

def _env_enabled(name: str, default: bool = False) -> bool:
    """True when an ARGO feature flag is switched on in the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    for marker, old, new in (
        ("avatar-motion.js allowlisted", OLD_ASSET, NEW_ASSET),
        ("/v2/motion-lab route", OLD_ROUTE, NEW_ROUTE),
    ):
        if old not in text:
            if new.strip() in text:
                print(f"  = {marker} (already applied)")
                continue
            print(f"  FAIL {marker}: anchor not found")
            return 1
        text = text.replace(old, new, 1)
        print(f"  + {marker}")

    if "def _env_enabled(" not in text:
        # Place it just before the request handler class so it is defined at
        # import time regardless of where the route lives.
        anchor = "\nclass "
        idx = text.find(anchor)
        if idx == -1:
            print("  FAIL: could not find a class to anchor the helper before")
            return 1
        text = text[:idx] + HELPER + text[idx:]
        print("  + _env_enabled helper")
    else:
        print("  = _env_enabled helper (already present)")

    TARGET.write_text(text, encoding="utf-8")

    check = TARGET.read_text(encoding="utf-8")
    print()
    print("  read-back audit:")
    for probe in (
        "'avatar-motion.js': ('assets'",
        "elif path == '/v2/motion-lab':",
        "ARGO_AVATAR_MOTION_LAB",
        "def _env_enabled(",
    ):
        print(f"    {'OK ' if probe in check else 'MISSING'} {probe}")

    import py_compile

    py_compile.compile(str(TARGET), doraise=True)
    print("    OK  compiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
