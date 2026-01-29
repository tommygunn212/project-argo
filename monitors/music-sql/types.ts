
export type ArgoState = 'IDLE' | 'LISTENING' | 'TRANSCRIBING' | 'THINKING' | 'SPEAKING' | 'ERROR' | 'INITIALIZING';

export interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  type: 'info' | 'error' | 'system' | 'vad' | 'llm' | 'stt';
}

export interface HardeningReport {
  overallScore: number;
  recommendations: Array<{
    title: string;
    description: string;
    impact: 'High' | 'Medium' | 'Low';
    category: 'Security' | 'Performance' | 'Stability';
    codeSnippet?: string;
  }>;
  bottlenecks: string[];
  architecturalRisks: string[];
}

export interface MetricPoint {
  time: string;
  stt: number;
  llm: number;
  tts: number;
  cpu: number;
}

export interface ArgoModule {
  name: string;
  filename: string;
  content: string;
}

export interface MusicIntentResult {
  artist: string | null;
  song: string | null;
  genre: string | null;
  era: string | null;
  confidence: number;
  systemAction: string;
  lookupMethod: 'SQL_DETERMINISTIC' | 'LLM_FALLBACK' | 'NOT_FOUND';
}
