#!/usr/bin/env python3
"""
Phase 5B - Latency Budget Enforcement
Monitor latencies against budgets and emit warnings/errors

No behavior changes - observation only
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

class BudgetStatus(Enum):
    """Budget compliance status"""
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"

@dataclass
class LatencyBudget:
    """Latency budget definition per profile"""
    profile: str
    first_token_ms: float  # Maximum time to first token
    total_response_ms: float  # Maximum total time

# Define budgets as data
LATENCY_BUDGETS = {
    "FAST": LatencyBudget(
        profile="FAST",
        first_token_ms=2000.0,
        total_response_ms=6000.0
    ),
    "ARGO": LatencyBudget(
        profile="ARGO",
        first_token_ms=3000.0,
        total_response_ms=10000.0
    ),
    "VOICE": LatencyBudget(
        profile="VOICE",
        first_token_ms=3000.0,
        total_response_ms=15000.0
    )
}

class LatencyBudgetEnforcer:
    """Monitor latencies against budgets, emit signals"""
    
    def __init__(self, profile: str = "FAST"):
        self.profile = profile.upper()
        self.budget = LATENCY_BUDGETS.get(self.profile)
        
        if not self.budget:
            raise ValueError(f"Unknown profile: {profile}")
    
    def check_first_token(self, elapsed_ms: float) -> BudgetStatus:
        """Check first-token latency against budget"""
        
        if elapsed_ms > self.budget.first_token_ms:
            logger.error(
                f"[LATENCY_BUDGET] First-token SLA VIOLATED: "
                f"{elapsed_ms:.0f}ms > {self.budget.first_token_ms}ms "
                f"(profile={self.profile})"
            )
            return BudgetStatus.ERROR
        elif elapsed_ms > self.budget.first_token_ms * 0.9:
            logger.warning(
                f"[LATENCY_BUDGET] First-token approaching budget: "
                f"{elapsed_ms:.0f}ms / {self.budget.first_token_ms}ms "
                f"({(elapsed_ms / self.budget.first_token_ms * 100):.0f}%)"
            )
            return BudgetStatus.WARN
        
        return BudgetStatus.OK
    
    def check_total_response(self, elapsed_ms: float) -> BudgetStatus:
        """Check total latency against budget"""
        
        if elapsed_ms > self.budget.total_response_ms:
            logger.error(
                f"[LATENCY_BUDGET] Total response SLA VIOLATED: "
                f"{elapsed_ms:.0f}ms > {self.budget.total_response_ms}ms "
                f"(profile={self.profile})"
            )
            return BudgetStatus.ERROR
        elif elapsed_ms > self.budget.total_response_ms * 0.9:
            logger.warning(
                f"[LATENCY_BUDGET] Total response approaching budget: "
                f"{elapsed_ms:.0f}ms / {self.budget.total_response_ms}ms "
                f"({(elapsed_ms / self.budget.total_response_ms * 100):.0f}%)"
            )
            return BudgetStatus.WARN
        
        return BudgetStatus.OK
    
    def check_all(self, first_token_ms: float, total_response_ms: float) -> dict:
        """Check both metrics and return status"""
        
        first_token_status = self.check_first_token(first_token_ms)
        total_status = self.check_total_response(total_response_ms)
        
        return {
            "profile": self.profile,
            "first_token": {
                "elapsed_ms": first_token_ms,
                "budget_ms": self.budget.first_token_ms,
                "status": first_token_status.value
            },
            "total": {
                "elapsed_ms": total_response_ms,
                "budget_ms": self.budget.total_response_ms,
                "status": total_status.value
            }
        }

# Module-level API for easy use
_enforcers = {}

def get_enforcer(profile: str = "FAST") -> LatencyBudgetEnforcer:
    """Get or create enforcer for profile"""
    key = profile.upper()
    if key not in _enforcers:
        _enforcers[key] = LatencyBudgetEnforcer(profile)
    return _enforcers[key]

def check_budget(profile: str, first_token_ms: float, total_response_ms: float) -> dict:
    """Check latencies against budget for profile"""
    enforcer = get_enforcer(profile)
    return enforcer.check_all(first_token_ms, total_response_ms)

if __name__ == "__main__":
    # Example usage
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    print("\nTest 1: FAST profile, compliant")
    result = check_budget("FAST", 1500, 5000)
    print(f"  First-token: {result['first_token']['status']}")
    print(f"  Total: {result['total']['status']}")
    
    print("\nTest 2: FAST profile, approaching warning")
    result = check_budget("FAST", 1900, 5400)
    print(f"  First-token: {result['first_token']['status']}")
    print(f"  Total: {result['total']['status']}")
    
    print("\nTest 3: FAST profile, SLA violated")
    result = check_budget("FAST", 2500, 7000)
    print(f"  First-token: {result['first_token']['status']}")
    print(f"  Total: {result['total']['status']}")
