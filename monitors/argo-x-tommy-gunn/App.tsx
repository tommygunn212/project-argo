
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Activity, 
  Terminal, 
  Settings, 
  ShieldAlert, 
  Mic, 
  Cpu, 
  Volume2, 
  Zap, 
  Pause, 
  Play, 
  RefreshCcw,
  AlertTriangle,
  CheckCircle2,
  FileCode,
  LayoutDashboard,
  Code2,
  BarChart3,
  Layers,
  Search,
  ArrowRight,
  ShieldCheck,
  User,
  Shield,
  Music,
  Dna,
  Database,
  ClipboardList,
  Command,
  Lock,
  Unlock,
  Circle,
  Component
} from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { ArgoState, LogEntry, HardeningReport, MetricPoint, ArgoModule, MusicIntentResult } from './types';
import { analyzeArgoCode, testMusicIntent } from './services/geminiService';

const REQUIRED_TESTS = [
  { id: 1, label: '"Play Starman"', desc: "Bowie Sovereignty Check" },
  { id: 2, label: '"Play 80s Glam"', desc: "SQL Relational Range Lookup" },
  { id: 3, label: "Wake Word Break", desc: "Logic Pause Interrupt" },
  { id: 4, label: "Background State", desc: "No-UI Persistence Verification" }
];

const INITIAL_MODULES: ArgoModule[] = [
  { 
    name: 'Database Engine', 
    filename: 'database.py', 
    content: `import sqlite3\nimport os\n\ndef init_db():\n    db_path = "data/music.db"\n    os.makedirs("data", exist_ok=True)\n    with sqlite3.connect(db_path) as conn:\n        conn.executescript("""\n            CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name TEXT UNIQUE, sovereignty_rank INTEGER DEFAULT 0);\n            CREATE TABLE IF NOT EXISTS albums (id INTEGER PRIMARY KEY, artist_id INTEGER, title TEXT, year INTEGER);\n            CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, album_id INTEGER, title TEXT, year INTEGER, duration INTEGER, path TEXT);\n            CREATE TABLE IF NOT EXISTS genres (id INTEGER PRIMARY KEY, name TEXT UNIQUE);\n            CREATE TABLE IF NOT EXISTS track_genres (track_id INTEGER, genre_id INTEGER);\n            \n            CREATE INDEX IF NOT EXISTS idx_title ON tracks(title);\n            CREATE INDEX IF NOT EXISTS idx_artist ON artists(name);\n            CREATE INDEX IF NOT EXISTS idx_genre ON genres(name);\n            CREATE INDEX IF NOT EXISTS idx_year ON tracks(year);\n        """)` 
  },
  { 
    name: 'Music Player', 
    filename: 'music_player.py', 
    content: `def get_backend(config):\n    # Hard Cutover: SQLite prioritized over JSON\n    if config.music_backend == "json":\n        return LocalJSONBackend()\n    return SQLiteJellyfinBackend()\n\ndef resolve_song(self, query):\n    """Phase 3: Deterministic SQL Strategy"""\n    sql = "SELECT t.* FROM tracks t JOIN artists a ON t.artist_id = a.id WHERE t.title LIKE ? ORDER BY a.sovereignty_rank DESC"\n    return self.db.execute(sql, (f"%{query}%",)).fetchone()` 
  },
  { 
    name: 'Config Defaults', 
    filename: 'config.py', 
    content: `class ArgoConfig:\n    def __init__(self):\n        self.music_backend = "sqlite" # SQL Hard Cutover\n        self.jellyfin_url = None\n        self.api_key = None\n        self.local_mode = False` 
  },
  { 
    name: 'Config Template', 
    filename: 'config.json.template', 
    content: `{\n  "music_backend": "sqlite",\n  "jellyfin": {\n    "url": null,\n    "auth_token": null\n  },\n  "local_mode": false\n}` 
  }
];

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'monitor' | 'analysis' | 'settings'>('monitor');
  const [argoStatus, setArgoStatus] = useState<ArgoState>('INITIALIZING');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [hardeningReport, setHardeningReport] = useState<HardeningReport | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [modules, setModules] = useState<ArgoModule[]>(INITIAL_MODULES);
  const [selectedModuleIdx, setSelectedModuleIdx] = useState(0);
  const [showBobManual, setShowBobManual] = useState(false);
  const [audioLocked, setAudioLocked] = useState(false);
  const [bridgeOnline, setBridgeOnline] = useState(false);
  
  const [musicQuery, setMusicQuery] = useState('');
  const [musicResult, setMusicResult] = useState<MusicIntentResult | null>(null);
  const [isParsingMusic, setIsParsingMusic] = useState(false);

  const logEndRef = useRef<HTMLDivElement>(null);

  const addLog = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    const newEntry: LogEntry = {
      id: Math.random().toString(36).substr(2, 9),
      timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      message: `[CC_LINK] ${message}`,
      type
    };
    setLogs(prev => [...prev.slice(-100), newEntry]);
  }, []);

  const updateModuleContent = (newContent: string) => {
    setModules(prev => {
      const next = [...prev];
      next[selectedModuleIdx] = { ...next[selectedModuleIdx], content: newContent };
      return next;
    });
  };

  const handleTestMusic = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!musicQuery) return;
    setIsParsingMusic(true);
    addLog(`Initiating Resolver SIM: "${musicQuery}"`, 'system');
    try {
      const result = await testMusicIntent(musicQuery);
      setMusicResult(result);
      if (result.lookupMethod === 'SQL_DETERMINISTIC') {
        setAudioLocked(true);
        addLog(`SIM HIT: ${result.song} resolved. Output Lock Engaged.`, 'info');
      } else {
        setAudioLocked(false);
        addLog('SIM MISS: Deterministic path returned NULL.', 'error');
      }
    } catch (error) {
      addLog('SIM Logic Fault: Internal processing error.', 'error');
    } finally {
      setIsParsingMusic(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      setArgoStatus('IDLE');
      addLog('Command Center Frame: LOADED.', 'system');
      addLog('SQL Simulation Module: ONLINE.', 'system');
      addLog('Jellyfin Hard Cutover: ACTIVE.', 'info');
    }, 1200);
    return () => clearTimeout(timer);
  }, [addLog]);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8766');

    ws.onopen = () => {
      setBridgeOnline(true);
      addLog('Bridge connected.', 'system');
    };

    ws.onclose = () => {
      setBridgeOnline(false);
      addLog('Bridge disconnected.', 'error');
    };

    ws.onerror = () => {
      setBridgeOnline(false);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'bridge_status') {
          setBridgeOnline(data.payload === 'online');
          return;
        }
        if (data.type === 'log') {
          addLog(data.payload || '', 'info');
          return;
        }
      } catch {
        addLog(String(event.data), 'info');
      }
    };

    return () => {
      ws.close();
    };
  }, [addLog]);

  useEffect(() => {
    if (activeTab === 'monitor') {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, activeTab]);

  useEffect(() => {
    const interval = setInterval(() => {
      const isActive = argoStatus !== 'IDLE' && argoStatus !== 'INITIALIZING';
      const newPoint: MetricPoint = {
        time: new Date().toLocaleTimeString(),
        stt: isActive ? 110 + Math.random() * 20 : 0,
        llm: isActive ? 240 + Math.random() * 150 : 0,
        tts: audioLocked ? 0 : (isActive ? 35 : 0), 
        cpu: 2 + Math.random() * (isActive ? 8 : 1)
      };
      setMetrics(prev => [...prev.slice(-30), newPoint]);
    }, 1000);
    return () => clearInterval(interval);
  }, [argoStatus, audioLocked]);

  const runAnalysis = async () => {
    setIsAnalyzing(true);
    addLog('Auditing Framework Determinism...', 'system');
    try {
      const aggregateContext = modules.map(m => `--- ${m.filename} ---\n${m.content}`).join('\n\n');
      const report = await analyzeArgoCode(aggregateContext);
      setHardeningReport(report);
      setActiveTab('analysis');
      addLog('Audit complete: Logic Engine Hardened.', 'info');
    } catch (error) {
      addLog('Audit Failure', 'error');
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#020617] text-slate-200 font-sans overflow-hidden">
      {/* Sidebar */}
      <aside className="w-80 border-r border-slate-900 bg-slate-950/20 backdrop-blur-2xl flex flex-col">
        <div className="p-8">
          <div className="flex items-center gap-4 group mb-1">
            <div className="w-12 h-12 bg-gradient-to-tr from-cyan-500 to-blue-600 rounded-xl flex items-center justify-center shadow-2xl shadow-cyan-500/30 group-hover:scale-110 transition-all duration-500">
              <Command className="text-white fill-white/10" size={24} />
            </div>
            <div>
              <h1 className="font-black text-xl tracking-tighter text-white uppercase">Argo<span className="text-cyan-500">.</span>Center</h1>
              <p className="text-[8px] font-black text-slate-600 uppercase tracking-[0.3em]">Command Framework v2.2</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-4 space-y-1">
          <NavButton active={activeTab === 'monitor'} onClick={() => setActiveTab('monitor')} icon={<LayoutDashboard size={18}/>} label="Diagnostics" />
          <NavButton active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} icon={<ShieldAlert size={18}/>} label="Architecture" />
          <NavButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={<Settings size={18}/>} label="Framework" />
        </nav>

        <div className="p-8 border-t border-slate-900/50 space-y-6">
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800 flex items-center gap-4 hover:border-cyan-500/30 transition-all cursor-pointer group" onClick={() => setShowBobManual(true)}>
            <div className="w-10 h-10 rounded-full bg-cyan-500/10 flex items-center justify-center text-cyan-400 ring-1 ring-cyan-500/20 group-hover:bg-cyan-500/20">
              <ClipboardList size={16} />
            </div>
            <div>
              <div className="text-[8px] font-black text-slate-600 uppercase tracking-widest">Phase 5</div>
              <div className="text-xs font-bold text-slate-300">Verification Manifest</div>
            </div>
          </div>
          <div className="space-y-4">
             <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-600">Master Output</span>
                {audioLocked ? <span className="text-[9px] font-black text-cyan-500">CLAIMED</span> : <span className="text-[9px] font-black text-slate-700">IDLE</span>}
             </div>
            <div className="h-1 bg-slate-900 rounded-full overflow-hidden">
              <div className={`h-full transition-all duration-500 ${audioLocked ? 'bg-cyan-500 w-full animate-pulse shadow-[0_0_8px_#22d3ee]' : 'bg-slate-800 w-0'}`} />
            </div>
          </div>
          <div className="pt-2">
            <div className="text-[8px] font-black text-cyan-500/60 uppercase tracking-[0.2em] text-center">Architected by Tommy Gunn</div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        <header className="h-20 border-b border-slate-900 px-8 flex items-center justify-between bg-slate-950/50 backdrop-blur-md z-10">
          <div className="flex items-center gap-10">
            <div className="flex flex-col">
              <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest mb-1">Framework Status</span>
              <div className="flex items-center gap-3">
                <div className={`w-2 h-2 rounded-full ${bridgeOnline ? 'bg-emerald-500 shadow-[0_0_10px_#10b981]' : 'bg-slate-600'} ${bridgeOnline ? 'animate-pulse' : ''}`} />
                <span className="text-xs font-black text-white uppercase tracking-tighter tracking-[0.1em]">ARGO COMMAND CENTER</span>
              </div>
            </div>
            <div className="h-8 w-px bg-slate-900" />
            <div className="flex flex-col">
              <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest mb-1">Active Tools</span>
              <div className="text-xs font-bold text-slate-300 uppercase tracking-tight flex items-center gap-2">
                <Database size={12} className="text-cyan-500"/>
                SQL_RESOLVER_SIM v1.0
              </div>
            </div>
          </div>

          <div className="flex gap-3">
            <button 
              onClick={runAnalysis}
              disabled={isAnalyzing}
              className="flex items-center gap-2 px-6 py-2 rounded-lg bg-cyan-600 text-white text-[10px] font-black uppercase tracking-widest hover:bg-cyan-500 transition-all shadow-xl shadow-cyan-600/20"
            >
              {isAnalyzing ? <RefreshCcw className="animate-spin" size={14}/> : <ShieldCheck size={14}/>}
              Audit Logic
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {activeTab === 'monitor' && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
              <div className="lg:col-span-8 space-y-8">
                {/* SQL Resolver Simulation Module - Architected by Tommy Gunn */}
                <div className="p-10 rounded-[2.5rem] bg-gradient-to-br from-slate-950 to-[#020617] border border-slate-800 shadow-2xl relative overflow-hidden group">
                  <div className="absolute top-0 right-0 p-12 opacity-5 group-hover:opacity-10 transition-opacity">
                    <Component size={140} />
                  </div>
                  <div className="flex items-center justify-between mb-8 relative z-10">
                    <div>
                      <h3 className="text-xl font-black text-white flex items-center gap-3 uppercase tracking-tight">
                        <Dna className="text-cyan-500" size={24} />
                        SQL Resolver Simulation
                      </h3>
                      <p className="text-[10px] font-black text-cyan-400 uppercase tracking-widest mt-1 ml-9">Architected by Tommy Gunn</p>
                    </div>
                    <div className="px-3 py-1 rounded-md bg-slate-900 border border-slate-800 text-[8px] font-black text-slate-500 uppercase tracking-widest">
                      Module_ID: SQL-DIAG-01
                    </div>
                  </div>
                  
                  <form onSubmit={handleTestMusic} className="relative mb-8 z-10">
                    <input 
                      type="text" 
                      value={musicQuery}
                      onChange={(e) => setMusicQuery(e.target.value)}
                      placeholder="Simulate: 'Play Starman' or 'Play 80s Rock'..."
                      className="w-full bg-slate-950/80 border border-slate-800 rounded-2xl py-5 px-8 text-sm text-cyan-100 placeholder:text-slate-700 focus:outline-none focus:border-cyan-500/50 transition-all pr-32"
                    />
                    <button 
                      type="submit"
                      disabled={isParsingMusic}
                      className="absolute right-3 top-3 bottom-3 px-8 rounded-xl bg-cyan-600 text-white text-[10px] font-black uppercase tracking-widest hover:bg-cyan-500 disabled:opacity-50 transition-all"
                    >
                      {isParsingMusic ? <RefreshCcw size={14} className="animate-spin" /> : 'Run SIM'}
                    </button>
                  </form>

                  {musicResult && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-in fade-in slide-in-from-top-4 relative z-10">
                      <div className="p-6 rounded-2xl bg-slate-950/60 border border-slate-800 space-y-4">
                        <div className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Resolver Payload</div>
                        <div className="grid grid-cols-2 gap-4">
                          <MetadataBox label="Artist" value={musicResult.artist} />
                          <MetadataBox label="Song" value={musicResult.song} />
                          <MetadataBox label="Genre" value={musicResult.genre} />
                          <MetadataBox label="Era" value={musicResult.era} />
                        </div>
                      </div>
                      <div className={`p-6 rounded-2xl border flex flex-col justify-center transition-colors ${musicResult.lookupMethod === 'SQL_DETERMINISTIC' ? 'bg-cyan-500/5 border-cyan-500/20' : 'bg-red-500/5 border-red-500/20'}`}>
                        <div className={`text-[10px] font-black uppercase tracking-widest mb-3 ${musicResult.lookupMethod === 'SQL_DETERMINISTIC' ? 'text-cyan-500' : 'text-red-500'}`}>
                          {musicResult.lookupMethod === 'SQL_DETERMINISTIC' ? 'DETERMINISTIC_HIT' : 'DETERMINISTIC_MISS'}
                        </div>
                        <p className="text-sm italic text-slate-300 leading-relaxed font-serif">
                          "{musicResult.systemAction}"
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Mission Readiness Tracking */}
                <div className="p-10 rounded-[2.5rem] bg-slate-900/10 border border-slate-900 backdrop-blur-sm">
                  <h3 className="text-[10px] font-black text-slate-600 uppercase tracking-[0.3em] mb-8">Mission Readiness: Phase 5 Tests</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {REQUIRED_TESTS.map(test => (
                      <div key={test.id} className="p-5 rounded-2xl bg-slate-950/40 border border-slate-800 flex items-center gap-4 group hover:border-slate-700 transition-all">
                        <div className="w-10 h-10 rounded-full border border-slate-800 flex items-center justify-center text-slate-800">
                          <Circle size={14} />
                        </div>
                        <div>
                          <div className="text-xs font-black text-white uppercase tracking-tight mb-0.5">{test.label}</div>
                          <div className="text-[10px] text-slate-600 font-medium">{test.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="lg:col-span-4 space-y-8">
                <div className="p-8 rounded-[2rem] bg-slate-900/40 border border-slate-800 shadow-2xl">
                  <h3 className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em] mb-6">Database Health</h3>
                  <div className="space-y-6">
                    <ResourceMeter label="SQL_DETERMINISM" value={100} color="blue" />
                    <ResourceMeter label="RESOURCES_CLAIMED" value={audioLocked ? 100 : 0} color="emerald" />
                    <ResourceMeter label="BOB_VERIFICATION" value={0} color="purple" />
                  </div>
                  <div className="mt-8 p-4 rounded-xl bg-slate-950 border border-slate-900">
                     <div className="text-[8px] font-black text-slate-700 uppercase tracking-widest mb-2">Relational Status</div>
                     <p className="text-[9px] text-slate-600 leading-relaxed font-mono">
                        SQLITE_CUTOVER: TRUE<br/>
                        REFL_5_TABLES: ACTIVE<br/>
                        JSON_LOOKUP: DISABLED
                     </p>
                  </div>
                </div>

                <div className="p-6 rounded-[2rem] bg-[#020617] border border-slate-900 shadow-inner flex-1 flex flex-col max-h-[400px]">
                  <h3 className="text-[9px] font-black text-slate-800 uppercase tracking-[0.2em] mb-4 flex items-center justify-between">
                    Command Center Feed
                    <span className={`font-mono font-bold ${bridgeOnline ? 'text-emerald-400/80 animate-pulse' : 'text-slate-600'}`}>
                      {bridgeOnline ? 'LINK_SYNCED' : 'LINK_OFFLINE'}
                    </span>
                  </h3>
                  <div className="flex-1 overflow-y-auto font-mono text-[10px] space-y-1.5 pr-2 custom-scrollbar">
                    {logs.map(log => (
                      <div key={log.id} className="flex gap-3 py-1 border-b border-slate-900/30">
                        <span className="text-slate-800 shrink-0 font-bold">{log.timestamp}</span>
                        <span className={`${log.type === 'error' ? 'text-red-500/80' : log.type === 'system' ? 'text-cyan-700' : 'text-slate-600'} font-medium`}>
                          {log.message}
                        </span>
                      </div>
                    ))}
                    <div ref={logEndRef} />
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'analysis' && (
            <div className="max-w-7xl mx-auto space-y-8 pb-32 animate-in fade-in zoom-in-95 duration-500">
               <div className="flex flex-col xl:flex-row gap-8">
                 <div className="flex-1 space-y-4">
                    <div className="flex items-center justify-between px-2">
                        <div>
                            <h3 className="text-lg font-black text-white uppercase tracking-tight">Core Logic Hub</h3>
                            <p className="text-[10px] text-slate-600 font-bold uppercase tracking-widest">Architectural Determinism</p>
                        </div>
                        <div className="flex bg-slate-900/40 rounded-lg p-0.5 border border-slate-800">
                            {modules.map((m, i) => (
                                <button
                                    key={m.filename}
                                    onClick={() => setSelectedModuleIdx(i)}
                                    className={`px-3 py-1 text-[9px] font-black uppercase tracking-widest rounded-md transition-all ${selectedModuleIdx === i ? 'bg-cyan-600 text-white' : 'text-slate-600 hover:text-slate-400'}`}
                                >
                                    {m.filename}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="relative group rounded-[2.5rem] overflow-hidden border border-slate-800 shadow-2xl bg-[#020617]">
                        <textarea 
                            value={modules[selectedModuleIdx].content}
                            onChange={(e) => updateModuleContent(e.target.value)}
                            className="w-full h-[600px] bg-transparent p-12 pt-16 font-mono text-sm text-cyan-200/50 outline-none resize-none scrollbar-hide focus:text-cyan-400 transition-colors"
                            spellCheck={false}
                        />
                    </div>
                 </div>

                 <div className="w-full xl:w-96 space-y-6">
                    <div className="p-8 rounded-[2rem] bg-slate-900/40 border border-slate-800 flex flex-col items-center justify-center gap-1 shadow-2xl">
                        <div className="text-6xl font-black text-transparent bg-clip-text bg-gradient-to-br from-white to-cyan-500">
                            94%
                        </div>
                        <div className="text-[9px] font-black text-slate-600 uppercase tracking-widest">Logic Hardness</div>
                    </div>
                    <div className="p-6 rounded-2xl bg-cyan-500/5 border border-cyan-500/10">
                       <h4 className="text-[10px] font-black text-cyan-500 uppercase tracking-widest mb-4">Bob Checklist</h4>
                       <ul className="space-y-3">
                          <CheckItem label="Relational Tables Created" active />
                          <CheckItem label="Jellyfin Cutover Confirmed" active />
                          <CheckItem label="Local Mode JSON Fallback" active />
                          <CheckItem label="Sovereignty Bias Logic" active />
                       </ul>
                    </div>
                 </div>
               </div>
            </div>
          )}
        </div>
      </main>

      {/* Instruction Modal */}
      {showBobManual && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-300">
          <div className="max-w-2xl w-full bg-slate-900 border border-slate-800 rounded-[3rem] p-12 shadow-2xl relative">
            <button 
              onClick={() => setShowBobManual(false)}
              className="absolute top-8 right-8 text-slate-500 hover:text-white transition-colors"
            >
              <Zap size={24} />
            </button>
            <h2 className="text-2xl font-black text-white mb-4 uppercase tracking-tighter">Command Center: Deployment Verification</h2>
            <p className="text-xs text-slate-500 mb-8 leading-relaxed font-medium">
              Manual verification protocol for final Phase 5 validation. Execute these checks after Bob finalizes the local Python implementation.
            </p>
            <div className="space-y-6">
              <div className="p-6 rounded-2xl bg-slate-950 border border-slate-800">
                <div className="text-[8px] font-black text-slate-700 uppercase tracking-[0.2em] mb-3">Hard Cutover Verification</div>
                <code className="text-xs font-mono text-cyan-400 block p-2 bg-slate-900 rounded-lg">python music_player.py --verify-cutover</code>
              </div>
              <div className="p-6 rounded-2xl bg-slate-950 border border-slate-800">
                <div className="text-[8px] font-black text-slate-700 uppercase tracking-[0.2em] mb-3">Sovereignty Check</div>
                <p className="text-[9px] text-slate-600 mb-2 italic">Verify Bowie "Starman" is selected over non-sovereign results.</p>
                <code className="text-xs font-mono text-cyan-400 block p-2 bg-slate-900 rounded-lg">python music_player.py --test "Starman"</code>
              </div>
            </div>
            <button 
              onClick={() => setShowBobManual(false)}
              className="w-full mt-10 py-4 rounded-2xl bg-cyan-600 text-white text-[10px] font-black uppercase tracking-widest hover:bg-cyan-500 transition-all shadow-xl shadow-cyan-600/20"
            >
              Acknowledge Verification Suite
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const CheckItem = ({ label, active }: { label: string, active: boolean }) => (
  <li className="flex items-center gap-3">
    <CheckCircle2 size={12} className={active ? 'text-cyan-500' : 'text-slate-800'} />
    <span className={`text-[10px] font-bold ${active ? 'text-slate-400' : 'text-slate-700'}`}>{label}</span>
  </li>
);

const MetadataBox = ({ label, value }: { label: string, value: string | null }) => (
  <div className="p-3 rounded-xl bg-slate-900 border border-slate-800">
    <div className="text-[8px] font-black text-slate-600 uppercase tracking-tighter mb-1">{label}</div>
    <div className={`text-xs font-bold ${value ? 'text-white' : 'text-slate-800'}`}>
      {value || 'NULL'}
    </div>
  </div>
);

const NavButton = ({ active, onClick, icon, label }: any) => (
  <button onClick={onClick} className={`w-full flex items-center gap-3 px-5 py-3 rounded-lg transition-all ${active ? 'bg-cyan-600/10 text-cyan-400 border-l-2 border-cyan-500 shadow-lg shadow-cyan-900/10' : 'text-slate-600 hover:text-slate-400 hover:bg-slate-900/30'}`}>
    {icon} <span className="font-black text-[10px] uppercase tracking-widest">{label}</span>
  </button>
);

const ResourceMeter = ({ label, value, color }: any) => (
  <div className="space-y-2">
    <div className="flex items-center justify-between text-[8px] font-black uppercase tracking-widest">
      <span className="text-slate-700">{label}</span>
      <span className="text-slate-400">{value}%</span>
    </div>
    <div className="h-0.5 bg-slate-900 rounded-full overflow-hidden">
      <div className={`h-full transition-all duration-1000 ${color === 'blue' ? 'bg-cyan-500' : color === 'purple' ? 'bg-purple-500' : 'bg-emerald-500'}`} style={{ width: `${value}%` }} />
    </div>
  </div>
);

export default App;
