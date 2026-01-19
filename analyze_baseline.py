"""
TASK 15 PART B: BASELINE ANALYSIS & SUMMARY

Analyzes the latency_baseline_measurements.json and generates a summary report
with key findings for identifying optimization opportunities.
"""

import json
import sys
from pathlib import Path


def analyze_baseline():
    """Analyze baseline measurements and print summary report."""
    
    baseline_file = Path("latency_baseline_measurements.json")
    
    if not baseline_file.exists():
        print("[ERROR] latency_baseline_measurements.json not found")
        print("[!] Run task_15_baseline_measurements.py or task_15_baseline_measurements_dryrun.py first")
        sys.exit(1)
    
    print("=" * 80)
    print("TASK 15 PART B: BASELINE ANALYSIS & FINDINGS")
    print("=" * 80)
    print()
    
    # Load baseline data
    with open(baseline_file) as f:
        baseline = json.load(f)
    
    print(f"Measurement timestamp: {baseline['timestamp']}")
    print(f"Total interactions: {baseline['total_interactions']}")
    print(f"Sessions: {baseline['num_sessions']}")
    print()
    
    # ===== STAGE BREAKDOWN =====
    print("=" * 80)
    print("LATENCY BREAKDOWN BY STAGE")
    print("=" * 80)
    print()
    
    stages_data = baseline["stages"]
    
    # Calculate percentages
    total_avg = stages_data.get("total", {}).get("avg_ms", 0)
    
    print(f"{'Stage':<20} {'Count':>6} {'Min(ms)':>10} {'Avg(ms)':>10} {'Max(ms)':>10} {'% Total':>8}")
    print("-" * 80)
    
    # Sort by average latency (descending) to see slowest first
    sorted_stages = sorted(
        [(k, v) for k, v in stages_data.items() if k != "total"],
        key=lambda x: x[1].get("avg_ms", 0),
        reverse=True
    )
    
    for stage_name, stage_data in sorted_stages:
        count = stage_data.get("count", 0)
        min_ms = stage_data.get("min_ms", 0)
        avg_ms = stage_data.get("avg_ms", 0)
        max_ms = stage_data.get("max_ms", 0)
        percent = (avg_ms / total_avg * 100) if total_avg > 0 else 0
        
        print(
            f"{stage_name:<20} {count:>6} {min_ms:>10.2f} {avg_ms:>10.2f} "
            f"{max_ms:>10.2f} {percent:>7.1f}%"
        )
    
    # Add total row
    if "total" in stages_data:
        total_data = stages_data["total"]
        print("-" * 80)
        print(
            f"{'TOTAL':<20} {total_data.get('count', 0):>6} "
            f"{total_data.get('min_ms', 0):>10.2f} {total_data.get('avg_ms', 0):>10.2f} "
            f"{total_data.get('max_ms', 0):>10.2f} {'100.0%':>8}"
        )
    
    print()
    
    # ===== KEY FINDINGS =====
    print("=" * 80)
    print("KEY FINDINGS")
    print("=" * 80)
    print()
    
    # Find slowest stage
    slowest_stage = max(sorted_stages, key=lambda x: x[1].get("avg_ms", 0))
    slowest_name, slowest_data = slowest_stage
    slowest_percent = (slowest_data.get("avg_ms", 0) / total_avg * 100) if total_avg > 0 else 0
    
    print(f"1. SLOWEST STAGE: {slowest_name.upper()}")
    print(f"   - Average: {slowest_data.get('avg_ms', 0):.2f}ms ({slowest_percent:.1f}% of total)")
    print(f"   - Range: {slowest_data.get('min_ms', 0):.2f}ms to {slowest_data.get('max_ms', 0):.2f}ms")
    print()
    
    # Check for variance
    print("2. STAGE CONSISTENCY (Coefficient of Variation)")
    print("   High variance = unreliable response times")
    print()
    
    cv_stages = []
    for stage_name, stage_data in sorted_stages:
        count = stage_data.get("count", 0)
        if count > 1:
            samples = stage_data.get("samples", [])
            if samples:
                avg = sum(samples) / len(samples)
                variance = sum((x - avg) ** 2 for x in samples) / len(samples)
                std_dev = variance ** 0.5
                cv = (std_dev / avg * 100) if avg > 0 else 0
                cv_stages.append((stage_name, cv, std_dev, avg))
    
    cv_stages.sort(key=lambda x: x[1], reverse=True)
    
    for stage_name, cv, std_dev, avg in cv_stages:
        print(f"   {stage_name:<15} CV={cv:>6.1f}% (σ={std_dev:>6.2f}ms, μ={avg:>6.2f}ms)")
    
    print()
    
    # ===== RECOMMENDATIONS =====
    print("=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print()
    
    # Check if LLM is dominant
    if "llm" in stages_data:
        llm_data = stages_data["llm"]
        llm_percent = (llm_data.get("avg_ms", 0) / total_avg * 100) if total_avg > 0 else 0
        if llm_percent > 40:
            print(f"⚠ LLM DOMINATES ({llm_percent:.1f}% of total latency)")
            print("  Recommendation: LLM inference is the bottleneck")
            print("  Options:")
            print("  - Switch to faster LLM (e.g., smaller quantization)")
            print("  - Increase Ollama threads (currently optimized for local CPU)")
            print("  - Trade quality for speed (reduce max_tokens or temperature)")
            print()
    
    # Check for high variance stages
    high_variance_stages = [s for s in cv_stages if s[1] > 20]
    if high_variance_stages:
        print("⚠ HIGH VARIANCE DETECTED")
        for stage_name, cv, std_dev, avg in high_variance_stages:
            print(f"  {stage_name}: {cv:.1f}% variance")
        print("  Recommendation: System responsiveness is inconsistent")
        print("  Causes: Resource contention, garbage collection, audio jitter")
        print("  Options:")
        print("  - Run system in isolation (close other apps)")
        print("  - Profile to identify jitter source")
        print("  - Increase buffer sizes for audio capture")
        print()
    
    # Check for outliers
    print("⚠ OUTLIER DETECTION")
    outlier_count = 0
    for stage_name, stage_data in sorted_stages:
        samples = stage_data.get("samples", [])
        if samples:
            q1 = sorted(samples)[len(samples) // 4]
            q3 = sorted(samples)[3 * len(samples) // 4]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            
            outliers = [s for s in samples if s < lower_bound or s > upper_bound]
            if outliers:
                outlier_count += len(outliers)
                print(f"  {stage_name}: {len(outliers)} outlier(s)")
    
    if outlier_count == 0:
        print("  None detected - latency is stable")
    else:
        print(f"  Total: {outlier_count} outlier(s)")
        print("  Recommendation: Investigate spike causes (GC, disk I/O, network)")
    
    print()
    
    # ===== NEXT STEPS =====
    print("=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print()
    print("TASK 15 PART C: Hardware Tuning (if needed)")
    print("  - Microphone input gain (avoid clipping)")
    print("  - Porcupine wake word sensitivity (reduce false positives)")
    print("  - Audio sample rate (currently 16kHz - standard)")
    print("  - Buffer sizes (balance latency vs stability)")
    print()
    print("TASK 15 PART D: Reliability Testing")
    print("  - 10+ minute idle behavior (no false wakes)")
    print("  - Repeated wake cycles (consistent performance)")
    print("  - Rapid successive wakes (burst handling)")
    print("  - Silence after wake (timeout behavior)")
    print("  - Background noise (robustness)")
    print()


if __name__ == "__main__":
    analyze_baseline()
