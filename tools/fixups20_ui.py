"""Make the dashboard tell the truth about personality.

  - The selector is Smooth Voice's, in its own labelled box, argo first, every
    option with a plain-English description - populated from the server.
  - 'Active now' shows what the LIVE session is running (model / voice /
    personality / instruction fingerprint), from the record the worker writes.
  - 'Saved for next session' shows what a reconnect will use, and says so
    when it differs. A dropdown change never looks like it changed a session
    already in flight.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "frontend-v2" / "index.html"
s = io.open(p, encoding="utf-8").read()
log = []

def rep(old, new, label, marker=None):
    global s
    if (marker or new) in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS x{s.count(old)}: {label}"
    s = s.replace(old, new, 1); log.append(f"OK   {label}")

# --- 1. info card: add 'Saved for next' row and an instructions row ---------------
rep('''          <div class="config-item">
            <span class="config-key">Personality</span>
            <span class="config-val" id="infoPersonality">—</span>
          </div>''',
'''          <div class="config-item">
            <span class="config-key">Personality</span>
            <span class="config-val" id="infoPersonality">—</span>
          </div>
          <div class="config-item">
            <span class="config-key">Instructions</span>
            <span class="config-val" id="infoInstructions" title="fingerprint of exactly what the live session was told">—</span>
          </div>
          <div class="config-item">
            <span class="config-key">Saved for next</span>
            <span class="config-val" id="infoSavedNext" title="what the next Smooth Voice connection will use">—</span>
          </div>''',
"info card rows", marker='id="infoSavedNext"')

# --- 2. classic note: say exactly which controls are which ----------------------------
rep('''            These control the fallback pipeline only. They do not affect Smooth Voice.''',
'''            Speech-to-Text, Text-to-Speech and TTS Model below control the classic fallback pipeline only.
            They do not affect Smooth Voice. The Smooth Voice personality has its own box further down.''',
"classic note")

# --- 3. the selector: its own box, argo first, descriptions ---------------------------
rep('''          <!-- Row 2: TTS Model + Personality -->
          <div class="grid-2">
            <div>
              <label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:6px">TTS Model</label>
              <select id="ttsModelSelect" style="width:100%" onchange="handleTTSModelChange()">
                <option value="gpt-4o-mini-tts" selected>gpt-4o-mini-tts ★</option>
                <option value="tts-1">tts-1 (standard)</option>
                <option value="tts-1-hd">tts-1-hd (high quality)</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:6px">Personality</label>
              <select id="personalitySelect" style="width:100%" onchange="handlePersonalityChange(this)">
                <option value="tommy_gunn">Tommy Gunn — Sharp, witty</option>
                <option value="jarvis">Jarvis — Calm, formal</option>
                <option value="tommy_mix">Tommy Mix — Sharp + chaos</option>
                <option value="rick">Rick — Chaotic, funny</option>
                <option value="claptrap">Claptrap — Manic, energetic</option>
                <option value="plain">Plain — Minimal, flat</option>
              </select>
            </div>
          </div>''',
'''          <!-- Row 2: TTS Model (classic only) -->
          <div class="grid-2">
            <div>
              <label style="font-size:12px;color:var(--text-dim);display:block;margin-bottom:6px">TTS Model <span style="opacity:.6">(classic fallback only)</span></label>
              <select id="ttsModelSelect" style="width:100%" onchange="handleTTSModelChange()">
                <option value="gpt-4o-mini-tts" selected>gpt-4o-mini-tts ★</option>
                <option value="tts-1">tts-1 (standard)</option>
                <option value="tts-1-hd">tts-1-hd (high quality)</option>
              </select>
            </div>
            <div></div>
          </div>

          <!-- Smooth Voice personality: server-side, applies on the NEXT connection -->
          <div id="personalityBox" style="margin-top:14px;padding:12px 14px;border:1px solid var(--accent);border-radius:var(--radius);background:var(--bg-input)">
            <div style="font-family:var(--font-mono);font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Smooth Voice personality</div>
            <select id="personalitySelect" style="width:100%" onchange="handlePersonalityChange(this)">
              <option value="argo">ARGO — Warm, sharp conversation partner (default)</option>
              <option value="tommy_gunn">Tommy Gunn — Dry, observant, quietly confident</option>
              <option value="tommy_mix">Tommy Mix — Composed with a sarcastic streak</option>
              <option value="jarvis">Jarvis — Calm, precise, British composure</option>
              <option value="rick">Rick — Restless, blunt, always right underneath</option>
              <option value="claptrap">Claptrap — Loud, eager, delighted to help</option>
              <option value="plain">Plain — Flat and factual, no personality</option>
            </select>
            <div id="personalityDescription" style="font-size:12px;color:var(--text-secondary);margin-top:6px;line-height:1.45">Warm, sharp conversation partner - thinks with you, pushes back gently, dry wit when it fits. The default.</div>
            <div id="personalityApplies" style="font-size:11px;color:var(--text-dim);margin-top:6px">Saved on the server. Applies to the <b>next</b> Smooth Voice connection - a session that is already running keeps the personality it started with.</div>
          </div>''',
"personality box", marker='id="personalityBox"')

# --- 4. populate the selector from the server, and describe the choice ------------------
rep('''function applyServerPersonality(personality) {
  const name = String(personality || '').trim();
  if (!name) return;
  const select = $('personalitySelect');
  if (!select) return;''',
'''// Rebuild the selector from the server's list, so a persona added or reworded
// on the server never needs a dashboard edit. Argo comes first because the
// server lists it first.
function applyServerPersonas(personas) {
  const select = $('personalitySelect');
  if (!select || !Array.isArray(personas) || !personas.length) return;
  const current = select.value;
  const existing = Array.prototype.map.call(select.options, o => o.value).join(',');
  const incoming = personas.map(p => p.name).join(',');
  if (existing !== incoming) {
    select.innerHTML = '';
    for (const p of personas) {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = `${p.label} — ${p.description.replace(/\\.\\s*The default\\.$/, '')}${p.name === 'argo' ? ' (default)' : ''}`;
      opt.dataset.description = p.description;
      select.appendChild(opt);
    }
    if (personas.some(p => p.name === current)) select.value = current;
  } else {
    for (const opt of select.options) {
      const p = personas.find(x => x.name === opt.value);
      if (p) opt.dataset.description = p.description;
    }
  }
  describePersonality(select);
}

function describePersonality(select) {
  const el = $('personalityDescription');
  if (!el || !select) return;
  const opt = select.options[select.selectedIndex];
  el.textContent = (opt && opt.dataset.description) || '';
}

function applyServerPersonality(personality) {
  const name = String(personality || '').trim();
  if (!name) return;
  const select = $('personalitySelect');
  if (!select) return;''',
"applyServerPersonas + describePersonality", marker="function applyServerPersonas(")

rep('''  sendOverride('personality_mode', wanted);
  serverPersonality = wanted;
  saveDropdownSettings();
  updatePipelineDisplay();
  addSystemLog(`Personality set to ${wanted} — applies to the next Smooth Voice session`);''',
'''  sendOverride('personality_mode', wanted);
  serverPersonality = wanted;
  saveDropdownSettings();
  describePersonality(select);
  updatePipelineDisplay();
  const live = livekitMeta.activeNow && livekitMeta.activeNow.live;
  addSystemLog(live
    ? `Personality saved as ${wanted}. The current session stays ${livekitMeta.activeNow.personality} until you reconnect.`
    : `Personality saved as ${wanted} — applies to the next Smooth Voice session`);
  refreshRealtimeStatus();''',
"handlePersonalityChange honest log", marker="The current session stays")

# --- 5. status fill: carry active_now / saved_for_next / personas ----------------------------
rep('''    livekitMeta = {
      model: data.model || livekitMeta.model,
      voice: data.voice || livekitMeta.voice,
      room: data.room || livekitMeta.room,
      speakerIdentity: data.speaker_identity || livekitMeta.speakerIdentity,
      avatar: data.avatar || livekitMeta.avatar,
      mobileUrl: livekitMeta.mobileUrl,
    };''',
'''    livekitMeta = {
      model: data.model || livekitMeta.model,
      voice: data.voice || livekitMeta.voice,
      room: data.room || livekitMeta.room,
      speakerIdentity: data.speaker_identity || livekitMeta.speakerIdentity,
      avatar: data.avatar || livekitMeta.avatar,
      mobileUrl: livekitMeta.mobileUrl,
      activeNow: data.active_now || null,
      savedForNext: data.saved_for_next || null,
    };
    applyServerPersonas(data.personas);''',
"livekitMeta carries active/saved", marker="activeNow: data.active_now")

rep('''  if (smooth) {
    set('infoBrain', data.model || '—');
    set('infoVoice', data.voice || '—');
  } else {''',
'''  const active = data.active_now && data.active_now.live ? data.active_now : null;
  const saved = data.saved_for_next || {};
  if (active) {
    // The live session's own record - what she is ACTUALLY running.
    set('infoBrain', `${active.model || '—'}  · live`);
    set('infoVoice', active.voice || '—');
    set('infoPersonality', active.personality || '—');
    set('infoInstructions', active.instruction_fingerprint || '—');
    const differs = saved.personality !== active.personality || saved.voice !== active.voice || saved.model !== active.model;
    set('infoSavedNext', differs
      ? `${saved.model} / ${saved.voice} / ${saved.personality}  (reconnect to apply)`
      : 'same as active');
  } else if (smooth) {
    set('infoBrain', `${saved.model || data.model || '—'}  · on connect`);
    set('infoVoice', saved.voice || data.voice || '—');
    set('infoPersonality', saved.personality || data.personality || '—');
    set('infoInstructions', saved.instruction_fingerprint || '—');
    set('infoSavedNext', 'no live session — this is what the next one will use');
  } else {''',
"active-now panel", marker="reconnect to apply")

rep('''  set('infoPersonality', data.personality || '—');

  const interruption = data.interruption || {};''',
'''  if (!active && !smooth) {
    set('infoPersonality', data.personality || '—');
    set('infoInstructions', '—');
    set('infoSavedNext', `${saved.voice || '—'} / ${saved.personality || '—'}`);
  }

  const interruption = data.interruption || {};''',
"classic branch keeps its rows", marker="if (!active && !smooth) {")

# --- 6. the pipeline line, when connected -------------------------------------------------------
rep('''    $('activePipelineDisplay').textContent =
      `Smooth Voice: ${livekitMeta.model} → ${livekitMeta.voice}`;''',
'''    const a = livekitMeta.activeNow && livekitMeta.activeNow.live ? livekitMeta.activeNow : null;
    $('activePipelineDisplay').textContent = a
      ? `Active now: ${a.model} / ${a.voice} / personality ${a.personality}  (${a.instruction_fingerprint || '—'})`
      : `Smooth Voice: ${livekitMeta.model} → ${livekitMeta.voice}  (session record pending)`;''',
"pipeline line shows Active now", marker="Active now: ${a.model}")

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("\n".join(log))
for needle in ('id="personalityBox"', 'function applyServerPersonas(', 'reconnect to apply', 'Active now: ${a.model}', 'value="argo"'):
    print(f"  {'OK  ' if needle in s else 'MISS'} {needle}")
