"""Discover Tommy's GE SmartHQ appliances and show what ARGO could control.

Read-only by default. Nothing is switched on or off unless --set is used, and
no credential ever reaches stdout, a log file or a traceback.

    python tools\\smart_home_probe.py              # air conditioners
    python tools\\smart_home_probe.py --all        # every GE appliance
    python tools\\smart_home_probe.py --state "bedroom"
    python tools\\smart_home_probe.py --set "bedroom" --on --temp 72
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import smart_home as sh  # noqa: E402


def _print_units(units) -> None:
    if not units:
        print("  no matching appliances reported by SmartHQ")
        return
    for unit in units:
        print(f"  {unit.name}")
        print(f"      type       : {unit.appliance_type}")
        print(f"      mac        : {unit.mac}")
        print(f"      online     : {unit.online}")
        print(f"      power      : {unit.power_on}")
        print(f"      room temp  : {unit.ambient_f}")
        print(f"      target     : {unit.target_f}")
        print(f"      mode / fan : {unit.mode} / {unit.fan}")
        print(f"      filter     : {unit.filter_status}")
        print(f"      spoken     : {unit.describe()}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe GE SmartHQ appliances")
    ap.add_argument("--all", action="store_true", help="include non-AC appliances")
    ap.add_argument("--state", metavar="NAME", help="show one unit's state")
    ap.add_argument("--set", metavar="NAME", dest="target", help="change one unit")
    ap.add_argument("--on", action="store_true", help="with --set: turn on")
    ap.add_argument("--off", action="store_true", help="with --set: turn off")
    ap.add_argument("--temp", type=int, metavar="F", help="with --set: target temperature")
    ap.add_argument("--mode", help="with --set: cool, heat, auto, dry, fan_only, energy_saver")
    ap.add_argument("--fan", help="with --set: auto, low, med, high")
    args = ap.parse_args()

    status = sh.credential_status()
    print("SmartHQ credentials")
    for key, value in status.items():
        print(f"  {key:14}: {value}")
    print()

    if not status["configured"]:
        print("Not configured. Add these two lines to I:\\argo\\.env and re-run:")
        print(f"  {sh.ENV_USER}=your-smarthq-email")
        print(f"  {sh.ENV_PASS}=your-smarthq-password")
        print()
        print("That is the same account the GE/SmartHQ phone app uses.")
        return 2

    try:
        if args.target:
            power = True if args.on else (False if args.off else None)
            if power is None and args.temp is None and not args.mode and not args.fan:
                print("--set needs at least one of --on/--off/--temp/--mode/--fan")
                return 2
            print(f"Changing {args.target!r} ...")
            unit = sh.ac_set(
                args.target, power=power, temperature_f=args.temp, mode=args.mode, fan=args.fan
            )
            print()
            _print_units([unit])
            return 0

        if args.state:
            print(f"State of {args.state!r}:")
            print()
            _print_units([sh.ac_state(args.state)])
            return 0

        label = "all appliances" if args.all else "air conditioners"
        print(f"Discovering {label} ...")
        print()
        _print_units(sh.discover(include_all=args.all))
        return 0

    except sh.SmartHomeError as exc:
        print(f"FAILED: {sh.redact(exc)}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"FAILED: {type(exc).__name__}: {sh.redact(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
