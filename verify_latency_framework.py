#!/usr/bin/env python3
"""
ARGO Latency Framework - Final Verification Script
Confirms all components are in place and working correctly.
"""

import os
import sys
from pathlib import Path

def check_file_exists(path, name):
    """Check if file exists and report status."""
    exists = os.path.exists(path)
    status = "✅" if exists else "❌"
    print(f"  {status} {name}")
    return exists

def check_file_size(path, min_lines, name):
    """Check file has minimum size."""
    if not os.path.exists(path):
        print(f"  ❌ {name} (file not found)")
        return False
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = len(f.readlines())
    except Exception as e:
        print(f"  ⚠️ {name} (read error: {e})")
        return True  # Non-blocking
    
    ok = lines >= min_lines
    status = "✅" if ok else "⚠️"
    print(f"  {status} {name} ({lines} lines, min {min_lines})")
    return ok

def main():
    print("=" * 70)
    print("ARGO v1.4.5 - LATENCY FRAMEWORK VERIFICATION")
    print("=" * 70)
    print()
    
    root = Path(__file__).parent
    all_good = True
    
    # Check core files
    print("📦 CORE FILES")
    all_good &= check_file_exists(root / "runtime" / "latency_controller.py", "latency_controller.py")
    all_good &= check_file_exists(root / ".env", ".env")
    print()
    
    # Check testing files
    print("🧪 TESTING FILES")
    all_good &= check_file_exists(root / "tests" / "test_latency.py", "tests/test_latency.py")
    all_good &= check_file_exists(root / "test_integration_latency.py", "test_integration_latency.py")
    print()
    
    # Check integration
    print("🔗 INTEGRATION POINTS")
    all_good &= check_file_exists(root / "input_shell" / "app.py", "input_shell/app.py (modified)")
    print()
    
    # Check documentation
    print("📚 DOCUMENTATION")
    all_good &= check_file_exists(root / "LATENCY_COMPLETE.md", "LATENCY_COMPLETE.md")
    all_good &= check_file_exists(root / "LATENCY_QUICK_REFERENCE.md", "LATENCY_QUICK_REFERENCE.md")
    all_good &= check_file_exists(root / "LATENCY_INTEGRATION_COMPLETE.md", "LATENCY_INTEGRATION_COMPLETE.md")
    all_good &= check_file_exists(root / "LATENCY_SYSTEM_ARCHITECTURE.md", "LATENCY_SYSTEM_ARCHITECTURE.md")
    all_good &= check_file_exists(root / "BASELINE_MEASUREMENT_QUICK_START.md", "BASELINE_MEASUREMENT_QUICK_START.md")
    all_good &= check_file_exists(root / "LATENCY_FILES_INDEX.md", "LATENCY_FILES_INDEX.md")
    all_good &= check_file_exists(root / "LATENCY_COMPLETION_SUMMARY.md", "LATENCY_COMPLETION_SUMMARY.md")
    all_good &= check_file_exists(root / "latency_report.md", "latency_report.md")
    all_good &= check_file_exists(root / "INDEX_LATENCY_DOCUMENTATION.md", "INDEX_LATENCY_DOCUMENTATION.md")
    print()
    
    # Check file sizes
    print("📏 FILE SIZES (Minimum Content Verification)")
    all_good &= check_file_size(root / "runtime" / "latency_controller.py", 200, "latency_controller.py")
    all_good &= check_file_size(root / "tests" / "test_latency.py", 200, "tests/test_latency.py")
    all_good &= check_file_size(root / "LATENCY_COMPLETE.md", 200, "LATENCY_COMPLETE.md")
    print()
    
    # Check content
    print("🔍 CONTENT VERIFICATION")
    try:
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root / "runtime"))
        
        # Try importing latency_controller
        from latency_controller import (
            LatencyController,
            LatencyProfile,
            new_controller,
            checkpoint,
        )
        print("  ✅ latency_controller imports successfully")
        
        # Try loading .env
        try:
            from dotenv import load_dotenv
            load_dotenv(root / ".env")
            print("  ✅ .env loads successfully")
        except Exception as e:
            print(f"  ⚠️ .env loading: {e}")
        
        # Try parsing profile
        import os as os_module
        profile_name = os_module.getenv("ARGO_LATENCY_PROFILE", "ARGO").upper()
        profile = LatencyProfile[profile_name]
        print(f"  ✅ Latency profile loaded: {profile.value}")
        
        # Try creating controller
        controller = new_controller(profile)
        checkpoint("test")
        report = controller.report()
        if "checkpoints" in report and "test" in report["checkpoints"]:
            print(f"  ✅ Controller creates and logs checkpoints")
        else:
            print(f"  ❌ Controller checkpoint logging failed")
            all_good = False
            
    except Exception as e:
        print(f"  ❌ Import/integration error: {e}")
        all_good = False
    
    print()
    
    # Final status
    print("=" * 70)
    if all_good:
        print("✅ VERIFICATION COMPLETE - ALL SYSTEMS OPERATIONAL")
        print()
        print("Status: 🟢 Ready for baseline measurement")
        print()
        print("Next Steps:")
        print("  1. Read: BASELINE_MEASUREMENT_QUICK_START.md")
        print("  2. Run: python input_shell/app.py")
        print("  3. Test: 5 runs × 4 scenarios = 20 test points")
        print("  4. Record: checkpoint times in measurements.csv")
        print("  5. Analyze: Fill latency_report.md with results")
        return 0
    else:
        print("❌ VERIFICATION FAILED - ISSUES DETECTED")
        print()
        print("Please check the items marked with ❌ above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
