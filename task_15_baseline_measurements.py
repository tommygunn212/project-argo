"""
TASK 15 PART B: BASELINE MEASUREMENTS COLLECTOR

Collects latency data from multiple real coordinator runs.
This script will:
1. Run coordinator multiple times
2. Collect aggregate latency stats from each run
3. Save baseline measurements to JSON
4. Print summary report

Requirement: 10+ real interactions to establish baseline
Current plan: Run 5 sessions × 3 interactions each = 15 total interactions

WARNING: This requires live audio input (microphone + speaker setup)
If you don't have a microphone, this will hang waiting for wake word.

PROTOCOL:
1. Run this script
2. For EACH interaction:
   - Wait for "Argo, " wake word prompt
   - Speak a simple command (e.g., "What time is it?")
   - Listen for response
   - System will automatically continue or exit
3. After all runs complete, baseline data is saved to latency_baseline_measurements.json
"""

import sys
import logging
import json
import os
from datetime import datetime

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def run_baseline_collection():
    """Collect 10+ baseline measurements by running multiple coordinator sessions."""
    
    print("=" * 80)
    print("TASK 15 PART B: BASELINE MEASUREMENTS COLLECTION")
    print("=" * 80)
    print()
    print("This will collect latency data from real coordinator runs.")
    print("Target: 10+ real interactions to establish baseline")
    print()
    print("Plan: Run 5 sessions × 3 interactions each = 15 interactions total")
    print()
    input("Press ENTER to start (make sure microphone/speaker are ready)...")
    print()
    
    try:
        from core.coordinator import Coordinator
        from core.input_trigger import PorcupineWakeWordTrigger
        from core.audio_capture import SimpleAudioCapture
        from core.speech_to_text import WhisperSTT
        from core.intent_parser import RuleBasedIntentParser
        from core.response_generator import ResponseGenerator
        from core.output_sink import EdgeTTSOutputSink
        from core.session_memory import SessionMemory
        
        print("[*] Pipeline layers imported successfully")
        
        # Will store ALL LatencyStats from each run
        all_stats = []
        
        # Run multiple sessions
        num_sessions = 5
        for session_num in range(1, num_sessions + 1):
            print()
            print("=" * 80)
            print(f"SESSION {session_num}/{num_sessions}")
            print("=" * 80)
            
            try:
                # Create fresh instances for each session
                trigger = PorcupineWakeWordTrigger(
                    access_key=os.environ.get("PORCUPINE_ACCESS_KEY"),
                    keywords=["argo"]
                )
                audio = SimpleAudioCapture(sample_rate=16000, chunk_size=512)
                stt = WhisperSTT(model="base")
                parser = RuleBasedIntentParser()
                generator = ResponseGenerator(api_key=os.environ.get("OLLAMA_API_KEY"))
                sink = EdgeTTSOutputSink()
                memory = SessionMemory(capacity=3)
                
                # Create and run coordinator
                coordinator = Coordinator(
                    trigger=trigger,
                    audio=audio,
                    stt=stt,
                    parser=parser,
                    generator=generator,
                    sink=sink,
                    memory=memory
                )
                
                print(f"[*] Coordinator v4 initialized for session {session_num}")
                print(f"[*] Max interactions per session: {coordinator.MAX_INTERACTIONS}")
                print(f"[*] Ready for interactions... (wake word: 'Argo,')")
                print()
                
                # Run coordinator (will loop until stop condition or max reached)
                coordinator.run()
                
                # Collect stats from this session
                session_stats = coordinator.latency_stats
                all_stats.append(session_stats)
                
                print()
                print(f"[OK] Session {session_num} complete - {coordinator.interaction_count} interactions")
                print(f"[OK] Aggregated latency data collected")
                
            except KeyboardInterrupt:
                print()
                print("[!] Session interrupted by user")
                raise
            except Exception as e:
                print(f"[ERROR] Session {session_num} failed: {e}")
                raise
        
        # ===== AGGREGATE ALL RUNS =====
        print()
        print("=" * 80)
        print("BASELINE MEASUREMENT COLLECTION COMPLETE")
        print("=" * 80)
        print()
        
        # Merge all stats
        from core.latency_probe import LatencyStats
        merged_stats = LatencyStats()
        
        total_interactions = 0
        for session_stats in all_stats:
            # Merge this session's data into merged_stats
            # Note: LatencyStats.stage_times is a dict of stage_name -> list of durations
            for stage_name, durations in session_stats.stage_times.items():
                if stage_name not in merged_stats.stage_times:
                    merged_stats.stage_times[stage_name] = []
                merged_stats.stage_times[stage_name].extend(durations)
            total_interactions += len(next(iter(session_stats.stage_times.values())))
        
        print(f"Total interactions measured: {total_interactions}")
        print()
        
        # Print merged report
        merged_stats.log_report()
        
        # Save baseline to JSON
        baseline_data = {
            "timestamp": datetime.now().isoformat(),
            "total_interactions": total_interactions,
            "num_sessions": num_sessions,
            "stages": {}
        }
        
        for stage_name, durations in merged_stats.stage_times.items():
            if durations:  # Only include if we have data
                baseline_data["stages"][stage_name] = {
                    "count": len(durations),
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                    "avg_ms": sum(durations) / len(durations),
                    "median_ms": sorted(durations)[len(durations) // 2],
                    "samples": durations  # Store raw samples for later analysis
                }
        
        # Save to JSON
        output_file = "latency_baseline_measurements.json"
        with open(output_file, "w") as f:
            json.dump(baseline_data, f, indent=2)
        
        print()
        print(f"[OK] Baseline measurements saved to: {output_file}")
        print()
        
        # Print summary
        print("=" * 80)
        print("BASELINE SUMMARY")
        print("=" * 80)
        print()
        for stage_name in sorted(baseline_data["stages"].keys()):
            stage_data = baseline_data["stages"][stage_name]
            print(f"{stage_name:20s}: avg={stage_data['avg_ms']:7.2f}ms (min={stage_data['min_ms']:7.2f}, max={stage_data['max_ms']:7.2f})")
        print()
        print("=" * 80)
        print("[OK] BASELINE MEASUREMENT COLLECTION SUCCESSFUL")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. Review baseline measurements in latency_baseline_measurements.json")
        print("2. Identify any slow stages or high variance")
        print("3. Run TASK 15 PART C to tune hardware if needed")
        print()
        
    except ImportError as e:
        print(f"[ERROR] Failed to import pipeline: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print("[!] Baseline collection interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Baseline collection failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_baseline_collection()
