"""Capabilities the realtime voice agent can call.

The classic pipeline reaches these through its _respond_with_* handlers. The
realtime worker runs in its own process and never imports the pipeline, so
without this module the model has nothing to call and refuses — which reads to
the user as ARGO losing abilities it used to have.

Every function here:
  - is safe to call from a worker thread (callers wrap in asyncio.to_thread),
  - returns a JSON-serialisable dict, never raises to the caller,
  - reports failure as {"ok": False, "error": ...} so the model can say what
    actually went wrong instead of inventing a result.

Filesystem access is confined to an allowlist. The ARGO install is always
readable; anything else must be granted by Tommy in config.json under
filesystem.allowed_folders. Granting is deliberately NOT callable by voice.

The capabilities are grouped by domain in the modules of this package and
re-exported here, so callers keep writing ``realtime_tools.pc_specs()``.
Tests that monkeypatch a module global must patch the submodule that uses it
(``realtime_tools.music.PLAYBACK_SETTLE_SECONDS``, not the package).
"""

from core.realtime_tools._base import ROOT, capability
from core.realtime_tools.apps import *  # noqa: F401,F403
from core.realtime_tools.files import *  # noqa: F401,F403
from core.realtime_tools.home import *  # noqa: F401,F403
from core.realtime_tools.knowledge import *  # noqa: F401,F403
from core.realtime_tools.machine import *  # noqa: F401,F403
from core.realtime_tools.music import *  # noqa: F401,F403
from core.realtime_tools.video import *  # noqa: F401,F403
from core.realtime_tools.writing import *  # noqa: F401,F403
