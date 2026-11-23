"""MilkDrop favorites: the preset cycling logic, run in node with stubs for the browser."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "frontend-v2" / "assets" / "milkdrop-visuals.js"
HARNESS = r"""
const fs = require('fs');
const store = {};
const loaded = [];
class Ctx { constructor(){ this.state='running'; } createOscillator(){ return {frequency:{},connect(){},start(){}}; }
  createGain(){ return {gain:{},connect(){}}; } resume(){} }
const win = {
  AudioContext: Ctx, devicePixelRatio: 1,
  localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  butterchurn: { createVisualizer: () => ({ loadPreset: p => loaded.push(p.id), connectAudio(){}, disconnectAudio(){}, render(){}, setRendererSize(){} }) },
  butterchurnPresets: { getPresets: () => ({ a:{id:'a'}, b:{id:'b'}, c:{id:'c'}, d:{id:'d'}, e:{id:'e'} }) },
};
global.window = win; global.document = { createElement: () => ({ getContext: () => ({}), style: {} }), hidden: false };
global.performance = { now: () => 0 };
global.requestAnimationFrame = () => 0;
eval(fs.readFileSync(process.env.MD_SCRIPT, 'utf8').replace(/\}\)\(typeof window.*$/s, '') + '})(window);');
const canvas = { getBoundingClientRect: () => ({ width: 100, height: 100 }), parentElement: null, offsetParent: {} };
const out = {};
const M = win.MilkdropVisuals;
%SCENARIO%
console.log(JSON.stringify(out));
"""


def run(scenario: str, saved: dict | None = None) -> dict:
    if not shutil.which("node"):
        pytest.skip("node not installed")
    pre = "".join(f"store[{json.dumps(k)}] = {json.dumps(v)};" for k, v in (saved or {}).items())
    code = HARNESS.replace("%SCENARIO%", pre + scenario)
    res = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30,
                         env={**os.environ, "MD_SCRIPT": str(SCRIPT)})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_favorites_toggle_and_persist():
    out = run("""
      M.init([canvas]);
      const first = M.presetName;
      out.added = M.toggleFavorite();
      out.favs = M.favorites;
      out.first = first;
      out.stored = store.argoMilkdropFaves;
      out.removed = M.toggleFavorite();
      out.after = M.favorites;
    """)
    assert out["added"] is True and out["favs"] == [out["first"]] and json.loads(out["stored"]) == [out["first"]]
    assert out["removed"] is False and out["after"] == []


def test_favorites_only_visits_just_the_favorites_both_directions():
    out = run("""
      M.init([canvas]);
      out.seq = [];
      out.faves = [];
      M.setFavoritesOnly(true);          // no favorites yet: still cycles everything
      const seen = new Set(); for (let i = 0; i < 6; i++) { M.next(); seen.add(M.presetName); }
      out.allSeen = seen.size;
      M.toggleFavorite(); const a = M.presetName;
      M.setFavoritesOnly(false);
      M.next(); M.next(); M.toggleFavorite(); const b = M.presetName;
      M.setFavoritesOnly(true);
      out.picked = [a, b];
      for (let i = 0; i < 6; i++) { M.next(); out.seq.push(M.presetName); }
      for (let i = 0; i < 4; i++) { M.prev(); out.seq.push(M.presetName); }
    """)
    assert out["allSeen"] == 5
    assert set(out["seq"]) <= set(out["picked"]) and len(set(out["seq"])) == 2


def test_saved_favorites_and_mode_survive_a_reload_and_bad_data_is_ignored():
    out = run("""
      M.init([canvas]);
      out.favs = M.favorites; out.only = M.favoritesOnly; out.name = M.presetName;
    """, saved={"argoMilkdropFaves": json.dumps(["c", "missing"]), "argoMilkdropFavesOnly": "1"})
    assert out["favs"] == ["c", "missing"] and out["only"] is True and out["name"] == "c"
    junk = run("M.init([canvas]); out.favs = M.favorites; out.ok = true;",
               saved={"argoMilkdropFaves": "{not json"})
    assert junk["favs"] == [] and junk["ok"] is True
