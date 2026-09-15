"""Put the Smooth Voice voice selector in the UI, next to the personality one.

Both are Smooth Voice controls, both are server-side, both apply on the NEXT
connection. Keeping them in one box is the point: the classic Text-to-Speech
dropdown is three inches away and does something completely different.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "frontend-v2" / "index.html"
s = io.open(p, encoding="utf-8").read()
log = []

def rep(old, new, label, marker):
    global s
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS x{s.count(old)}: {label}"
    s = s.replace(old, new, 1); log.append(f"OK   {label}")

# --- the selector, above the personality one ------------------------------------
rep('''            <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Smooth Voice personality</div>
            <select id="personalitySelect" style="width:100%" onchange="handlePersonalityChange(this)">''',
'''            <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Smooth Voice — voice &amp; personality</div>
            <label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:4px">Voice</label>
            <select id="realtimeVoiceSelect" style="width:100%;margin-bottom:10px" onchange="handleRealtimeVoiceChange(this)">
              <option value="marin">Marin — warm, natural (default)</option>
              <option value="cedar">Cedar — warm, lower</option>
              <option value="alloy">Alloy — balanced, neutral</option>
              <option value="ash">Ash — clear, even</option>
              <option value="ballad">Ballad — soft, expressive</option>
              <option value="coral">Coral — bright, friendly</option>
              <option value="echo">Echo — crisp, measured</option>
              <option value="sage">Sage — calm, steady</option>
              <option value="shimmer">Shimmer — light, quick</option>
              <option value="verse">Verse — rich, narrative</option>
            </select>
            <label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:4px">Personality</label>
            <select id="personalitySelect" style="width:100%" onchange="handlePersonalityChange(this)">''',
"voice selector markup", marker='id="realtimeVoiceSelect"')

# --- handler + server reconciliation ----------------------------------------------
rep('''function describePersonality(select) {''',
'''function handleRealtimeVoiceChange(select) {
  const wanted = select.value;
  const connected = (typeof ws !== 'undefined') && ws && ws.readyState === WebSocket.OPEN;
  if (!connected) {
    select.value = serverRealtimeVoice || select.value;
    addSystemLog(`Not saved — ARGO is offline. Voice stays ${select.value}.`);
    setRealtimeError('Voice change was not saved: no connection to ARGO.');
    return;
  }
  sendOverride('realtime_voice', wanted);
  serverRealtimeVoice = wanted;
  const live = livekitMeta.activeNow && livekitMeta.activeNow.live;
  addSystemLog(live
    ? `Voice saved as ${wanted}. The current session stays ${livekitMeta.activeNow.voice} until you reconnect.`
    : `Voice saved as ${wanted} — applies to the next Smooth Voice session`);
  refreshRealtimeStatus();
}

// Last voice confirmed by the server, so a failed change can be reverted.
let serverRealtimeVoice = null;

function applyServerRealtimeVoice(voice, voices) {
  const select = $('realtimeVoiceSelect');
  if (!select) return;
  if (Array.isArray(voices) && voices.length) {
    const incoming = voices.map(v => v.name).join(',');
    const existing = Array.prototype.map.call(select.options, o => o.value).join(',');
    if (incoming !== existing) {
      const current = select.value;
      select.innerHTML = '';
      for (const v of voices) {
        const opt = document.createElement('option');
        opt.value = v.name; opt.textContent = v.label;
        select.appendChild(opt);
      }
      if (voices.some(v => v.name === current)) select.value = current;
    }
  }
  const name = String(voice || '').trim();
  if (!name) return;
  serverRealtimeVoice = name;
  if (select.value !== name) select.value = name;
}

function describePersonality(select) {''',
"voice handler", marker="function handleRealtimeVoiceChange(")

# --- reconcile from the server's SAVED value, not the live one -----------------------
rep('''    applyServerPersonas(data.personas);''',
'''    applyServerPersonas(data.personas);
    // Reconcile both selectors against what is SAVED for the next session.
    // Using the live session's values would make the dropdowns snap back to
    // whatever is currently talking, undoing a change he just made.
    const savedNext = data.saved_for_next || {};
    applyServerRealtimeVoice(savedNext.voice || data.voice, data.voices);''',
"reconcile voice from saved_for_next", marker="applyServerRealtimeVoice(savedNext.voice")

rep('''    applyServerPersonality(data.personality);''',
'''    applyServerPersonality((data.saved_for_next && data.saved_for_next.personality) || data.personality);''',
"personality reconciles from saved_for_next", marker="data.saved_for_next && data.saved_for_next.personality")

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("\n".join(log))
for needle in ('id="realtimeVoiceSelect"', 'handleRealtimeVoiceChange', 'applyServerRealtimeVoice', 'savedNext.voice'):
    print(f"  {'OK  ' if needle in s else 'MISS'} {needle}")
