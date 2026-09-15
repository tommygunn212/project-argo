"""Close the same-pid hole in SingleInstance. Run once from I:\\argo."""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "core" / "runtime_guard.py"
s = io.open(p, encoding="utf-8").read()
changed = []

def rep(old, new, label):
    global s
    if new in s:
        changed.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS: {label}"
    s = s.replace(old, new, 1); changed.append(f"OK   {label}")

rep('''        self.holder: dict | None = None''',
    '''        self.holder: dict | None = None
        self._held = False''', "track whether this object holds the lock")

rep('''            if pid != os.getpid() and _process_is_alive(pid, started):''',
    '''            # Deliberately NOT exempting our own pid. The threat being
            # guarded is a second holder of this ROLE, and exempting the pid
            # made the guard pass its own test for the wrong reason - a
            # second SingleInstance sailed straight through. A process that
            # legitimately re-takes its own lock holds the same object, which
            # is handled by the _held short-circuit above.
            if _process_is_alive(pid, started):''', "drop the same-pid exemption")

rep('''        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        existing = self._read()''',
    '''        if self._held:
            return self          # re-acquiring the same lock object is a no-op

        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        existing = self._read()''', "idempotent re-acquire on the same object")

rep('''        logger.info("[Lock] holding %s (pid %s)", self.role, os.getpid())''',
    '''        self._held = True
        logger.info("[Lock] holding %s (pid %s)", self.role, os.getpid())''', "mark held")

rep('''                logger.debug("[Lock] could not remove %s", self.path, exc_info=True)''',
    '''                logger.debug("[Lock] could not remove %s", self.path, exc_info=True)
        self._held = False''', "mark released")

io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s)
print("\n".join(changed))
