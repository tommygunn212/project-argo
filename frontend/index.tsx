import React, { useEffect, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';

// Simple types for our events
type SystemState = 'WAITING' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'WARMING_UP' | 'ERROR';

interface Metric {
  ttft: number;
  stt: number;
}

interface LogEntry {
  timestamp: string;
  message: string;
}

const App = () => {
  const [status, setStatus] = useState<SystemState>('WAITING');
  const [metrics, setMetrics] = useState<Metric>({ ttft: 0, stt: 0 });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<number | null>(null);

  const connect = () => {
    // Prevent multiple connections
    if (ws.current && (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)) {
        return;
    }

    const socket = new WebSocket('ws://localhost:8001/ws');
    ws.current = socket;

    socket.onopen = () => {
      addLog("Connected to ARGO Core");
      // Clear error status on connect if we were in error
      setStatus(prev => prev === 'ERROR' ? 'WAITING' : prev);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'status') {
          setStatus(data.payload);
        } else if (data.type === 'metric') {
          setMetrics(prev => ({ ...prev, ...data.payload }));
        } else if (data.type === 'log') {
          addLog(data.payload);
        }
      } catch (e) {
        console.error("Parse error", e);
      }
    };

    socket.onclose = () => {
      addLog("Disconnected... Retrying in 2s");
      setStatus('ERROR');
      // Auto-reconnect
      reconnectTimeout.current = window.setTimeout(connect, 2000);
    };

    socket.onerror = (e) => {
        // Error usually leads to close, so handled there, but good to log
        console.log("WebSocket error", e);
    };
  };

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      ws.current?.close();
      // Remove listener to prevent memory leaks if component unmounts during retry
      if (ws.current) ws.current.onclose = null; 
    };
  }, []);

  const addLog = (msg: string) => {
    setLogs(prev => [{ timestamp: new Date().toLocaleTimeString(), message: msg }, ...prev].slice(0, 50));
  };

  const getStatusColor = () => {
    switch (status) {
      case 'WAITING': return 'bg-gray-600';
      case 'LISTENING': return 'bg-red-500 animate-pulse';
      case 'PROCESSING': return 'bg-yellow-500';
      case 'SPEAKING': return 'bg-green-500';
      case 'WARMING_UP': return 'bg-blue-500';
      case 'ERROR': return 'bg-red-900';
      default: return 'bg-gray-800';
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 font-mono p-8 flex flex-col gap-6">
      
      {/* Header */}
      <div className="flex justify-between items-center border-b border-gray-700 pb-4">
        <h1 className="text-3xl font-bold tracking-tighter text-blue-400">ARGO <span className="text-sm text-gray-500">LOCAL CORE</span></h1>
        <div className={`px-4 py-2 rounded-full text-sm font-bold ${getStatusColor()}`}>
          {status}
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Metrics Panel */}
        <div className="bg-gray-800 p-6 rounded-lg border border-gray-700">
          <h2 className="text-xl mb-4 text-gray-400">Latency Metrics</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-900 p-4 rounded text-center">
              <div className="text-3xl font-bold text-yellow-400">{metrics.ttft.toFixed(0)}ms</div>
              <div className="text-xs text-gray-500 mt-1">Time to First Token</div>
            </div>
            <div className="bg-gray-900 p-4 rounded text-center">
              <div className="text-3xl font-bold text-blue-400">{metrics.stt.toFixed(0)}ms</div>
              <div className="text-xs text-gray-500 mt-1">Transcription Time</div>
            </div>
          </div>
        </div>

        {/* Status Panel */}
        <div className="bg-gray-800 p-6 rounded-lg border border-gray-700 flex items-center justify-center">
             {status === 'LISTENING' && (
                 <div className="text-center">
                     <div className="text-6xl mb-2">🎤</div>
                     <p>Listening...</p>
                 </div>
             )}
             {status === 'PROCESSING' && (
                 <div className="text-center">
                     <div className="text-6xl mb-2 animate-spin">⚙️</div>
                     <p>Processing...</p>
                 </div>
             )}
             {status === 'SPEAKING' && (
                 <div className="text-center">
                     <div className="text-6xl mb-2">🔊</div>
                     <p>Speaking...</p>
                 </div>
             )}
             {status === 'WAITING' && (
                 <div className="text-center text-gray-500">
                     <div className="text-6xl mb-2">💤</div>
                     <p>Waiting for wake word...</p>
                 </div>
             )}
              {status === 'WARMING_UP' && (
                 <div className="text-center text-blue-400">
                     <div className="text-6xl mb-2 animate-pulse">🧊</div>
                     <p>Warming Up Models...</p>
                 </div>
             )}
              {status === 'ERROR' && (
                 <div className="text-center text-red-500">
                     <div className="text-6xl mb-2">⚠️</div>
                     <p>Backend Disconnected</p>
                 </div>
             )}
        </div>
      </div>

      {/* Logs Terminal */}
      <div className="flex-1 bg-black p-4 rounded-lg border border-gray-700 overflow-hidden flex flex-col">
        <h2 className="text-sm text-gray-500 mb-2 border-b border-gray-800 pb-2">SYSTEM LOGS</h2>
        <div className="flex-1 overflow-y-auto font-mono text-sm space-y-1">
          {logs.map((log, i) => (
            <div key={i} className="flex gap-4">
              <span className="text-gray-600 shrink-0">[{log.timestamp}]</span>
              <span className={log.message.startsWith('User:') ? 'text-blue-300' : log.message.startsWith('Argo:') ? 'text-green-300' : 'text-gray-400'}>
                {log.message}
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
};

const root = createRoot(document.getElementById('root')!);
root.render(<App />);
