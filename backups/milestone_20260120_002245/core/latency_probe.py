"""
TASK 15: Latency Instrumentation Module

Timing probes for measuring end-to-end latency.

Records timestamps at key pipeline stages and computes durations.
No behavior changes. Logging only.
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LatencyProbe:
    """
    Single-session latency measurement.
    
    Records timestamps at 10 key points and computes stage durations.
    """
    
    def __init__(self, interaction_num: int):
        """Initialize probe for this interaction."""
        self.interaction_num = interaction_num
        self.timestamps: Dict[str, float] = {}
        self.durations: Dict[str, float] = {}
        self.start_time = datetime.now()
    
    def mark(self, event: str) -> None:
        """Record timestamp for an event."""
        import time
        self.timestamps[event] = time.time()
        logger.debug(f"[Latency] Interaction {self.interaction_num}: {event}")
    
    def compute_duration(self, start_event: str, end_event: str, label: str) -> Optional[float]:
        """Compute duration between two events (milliseconds)."""
        if start_event not in self.timestamps or end_event not in self.timestamps:
            return None
        
        duration_ms = (self.timestamps[end_event] - self.timestamps[start_event]) * 1000
        self.durations[label] = duration_ms
        return duration_ms
    
    def finalize(self) -> None:
        """Compute all stage durations."""
        # Stage durations
        self.compute_duration("wake_detected", "recording_start", "wake_to_record")
        self.compute_duration("recording_start", "recording_end", "recording")
        self.compute_duration("stt_start", "stt_end", "stt")
        self.compute_duration("parsing_start", "parsing_end", "parsing")
        self.compute_duration("llm_start", "llm_end", "llm")
        self.compute_duration("tts_start", "tts_end", "tts")
        
        # End-to-end
        self.compute_duration("wake_detected", "tts_end", "total")
    
    def get_summary(self) -> Dict[str, float]:
        """Get all computed durations."""
        return self.durations.copy()
    
    def log_summary(self) -> None:
        """Log all timings for this interaction."""
        self.finalize()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[Latency] Interaction {self.interaction_num} Summary")
        logger.info(f"{'='*60}")
        
        for stage, ms in sorted(self.durations.items()):
            logger.info(f"  {stage:20s}: {ms:8.2f} ms")
        
        logger.info(f"{'='*60}\n")


class LatencyStats:
    """
    Aggregate latency statistics across multiple interactions.
    """
    
    def __init__(self):
        """Initialize statistics accumulator."""
        self.interactions: Dict[int, LatencyProbe] = {}
        self.stage_times: Dict[str, list] = {}
    
    def add_probe(self, probe: LatencyProbe) -> None:
        """Add completed probe to statistics."""
        probe.finalize()
        self.interactions[probe.interaction_num] = probe
        
        # Accumulate stage times
        for stage, duration in probe.get_summary().items():
            if stage not in self.stage_times:
                self.stage_times[stage] = []
            self.stage_times[stage].append(duration)
    
    def get_stats(self, stage: str) -> Optional[Dict[str, float]]:
        """Get statistics for a specific stage."""
        if stage not in self.stage_times or len(self.stage_times[stage]) == 0:
            return None
        
        times = self.stage_times[stage]
        times_sorted = sorted(times)
        
        return {
            "count": len(times),
            "min": min(times),
            "max": max(times),
            "avg": sum(times) / len(times),
            "median": times_sorted[len(times_sorted) // 2],
        }
    
    def print_report(self) -> str:
        """Generate human-readable latency report."""
        report_lines = []
        report_lines.append("\n" + "="*80)
        report_lines.append("LATENCY REPORT (AGGREGATE)")
        report_lines.append("="*80)
        report_lines.append(f"Interactions measured: {len(self.interactions)}\n")
        
        # Sort stages by typical pipeline order
        stage_order = [
            "wake_to_record", "recording", "stt", "parsing", "llm", "tts", "total"
        ]
        
        report_lines.append(
            f"{'Stage':<20} {'Count':>6} {'Min(ms)':>10} {'Avg(ms)':>10} "
            f"{'Max(ms)':>10} {'Median(ms)':>10}"
        )
        report_lines.append("-" * 80)
        
        for stage in stage_order:
            stats = self.get_stats(stage)
            if stats:
                report_lines.append(
                    f"{stage:<20} {stats['count']:>6} "
                    f"{stats['min']:>10.2f} {stats['avg']:>10.2f} "
                    f"{stats['max']:>10.2f} {stats['median']:>10.2f}"
                )
        
        report_lines.append("="*80 + "\n")
        return "\n".join(report_lines)
    
    def log_report(self) -> None:
        """Log the aggregated report."""
        logger.info(self.print_report())
