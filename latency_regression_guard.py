#!/usr/bin/env python3
"""
Phase 5C - Latency Regression Guard
Detect performance regressions comparing against baselines

Warnings only - no test failures
"""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class RegressionThresholds:
    """Regression detection thresholds"""
    FIRST_TOKEN_PCT = 15.0  # Flag if > +15% slower
    TOTAL_RESPONSE_PCT = 20.0  # Flag if > +20% slower

class LatencyRegressionGuard:
    """Detect and warn about performance regressions"""
    
    def __init__(self, baselines_dir: Path = None):
        if baselines_dir is None:
            baselines_dir = Path(__file__).parent / "baselines"
        
        self.baselines_dir = baselines_dir
        self.baselines = {}
        
        # Load baseline files
        self._load_baselines()
    
    def _load_baselines(self) -> None:
        """Load baseline measurement files"""
        
        for profile in ["FAST", "VOICE"]:
            baseline_file = self.baselines_dir / f"latency_baseline_{profile}.json"
            
            if baseline_file.exists():
                try:
                    with open(baseline_file) as f:
                        data = json.load(f)
                        self.baselines[profile] = data
                        logger.debug(f"Loaded baseline for {profile}")
                except Exception as e:
                    logger.warning(f"Could not load {profile} baseline: {e}")
    
    def check_regression(
        self, 
        profile: str, 
        first_token_ms: float, 
        total_response_ms: float
    ) -> Tuple[bool, list]:
        """
        Check if current metrics regressed from baseline
        Returns: (has_regression, warnings)
        """
        
        profile = profile.upper()
        warnings = []
        
        if profile not in self.baselines:
            logger.debug(f"No baseline available for {profile}")
            return False, warnings
        
        baseline = self.baselines[profile]
        
        # Check first-token regression
        if "first_token_ms" in baseline:
            baseline_ft = baseline["first_token_ms"]
            threshold = baseline_ft * (1 + RegressionThresholds.FIRST_TOKEN_PCT / 100.0)
            
            if first_token_ms > threshold:
                pct_slower = ((first_token_ms - baseline_ft) / baseline_ft) * 100
                msg = (
                    f"[WARN] Latency regression detected ({profile}): "
                    f"First-token {pct_slower:.1f}% slower "
                    f"({first_token_ms:.0f}ms vs baseline {baseline_ft:.0f}ms)"
                )
                logger.warning(msg)
                warnings.append(msg)
        
        # Check total-response regression
        if "total_response_ms" in baseline:
            baseline_tr = baseline["total_response_ms"]
            threshold = baseline_tr * (1 + RegressionThresholds.TOTAL_RESPONSE_PCT / 100.0)
            
            if total_response_ms > threshold:
                pct_slower = ((total_response_ms - baseline_tr) / baseline_tr) * 100
                msg = (
                    f"[WARN] Latency regression detected ({profile}): "
                    f"Total response {pct_slower:.1f}% slower "
                    f"({total_response_ms:.0f}ms vs baseline {baseline_tr:.0f}ms)"
                )
                logger.warning(msg)
                warnings.append(msg)
        
        return len(warnings) > 0, warnings

# Module-level API
_guard: Optional[LatencyRegressionGuard] = None

def get_guard(baselines_dir: Path = None) -> LatencyRegressionGuard:
    """Get or create regression guard"""
    global _guard
    if _guard is None:
        _guard = LatencyRegressionGuard(baselines_dir)
    return _guard

def check_regression(
    profile: str,
    first_token_ms: float,
    total_response_ms: float
) -> Tuple[bool, list]:
    """Check for regression, returns (has_regression, warnings)"""
    guard = get_guard()
    return guard.check_regression(profile, first_token_ms, total_response_ms)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(message)s'
    )
    
    print("\nPhase 5C - Latency Regression Guard")
    print("="*60)
    
    guard = get_guard()
    
    # Test with hypothetical values
    print("\nTest 1: Check FAST baseline (if available)")
    has_regression, warnings = check_regression("FAST", 2100, 6200)
    if warnings:
        for w in warnings:
            print(w)
    else:
        print("[OK] No regressions detected (or no baseline loaded)")
    
    print("\nTest 2: Check VOICE baseline (if available)")
    has_regression, warnings = check_regression("VOICE", 3500, 11500)
    if warnings:
        for w in warnings:
            print(w)
    else:
        print("[OK] No regressions detected (or no baseline loaded)")
    
    print("\nRegression Guard Ready")
    print(f"Baselines loaded: {list(guard.baselines.keys())}")
