"""`python -m plugin_platform_libvirt ...`: the plugin from the command line (the platform app drives the same hooks
from its page). `status` prints the status as JSON (`--wake` reads idle daemons and the session too, which starts
them); a change is made at once, but forcing a machine off and reverting it to a snapshot are refused until asked again
with `--yes`, as the page asks a second time. `--session` is qemu:///session (the user's own); else qemu:///system."""
from __future__ import annotations

import argparse
import json
import sys

from liminal_libs.machines.plugin import CommandError

from . import MACHINE, Refusal

USAGE = ("python -m plugin_platform_libvirt status [--wake] | wake | start|shutdown|reboot NAME [--session] "
         "| destroy NAME [--session] [--yes] | autostart NAME on|off [--session] "
         "| snapshot NAME [SNAPSHOT] [--description TEXT] [--session] | revert NAME SNAPSHOT [--session] [--yes] "
         "| service UNIT start | run [--session] -- ARGS...")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m plugin_platform_libvirt", description="libvirt on this native Linux machine")
    sub = p.add_subparsers(dest="what")
    s = sub.add_parser("status", help="the status as JSON")
    s.add_argument("--wake", action="store_true", help="read idle daemons and the session too (connecting starts them)")
    sub.add_parser("wake", help="read idle daemons and the session now (connecting starts them)")

    def machine(verb: str, help_: str) -> argparse.ArgumentParser:
        v = sub.add_parser(verb, help=help_)
        v.add_argument("name")
        v.add_argument("--session", action="store_true", help="qemu:///session (the user's own)")
        return v
    for verb in ("start", "shutdown", "reboot"):
        machine(verb, f"{verb} a machine")
    machine("destroy", "force a machine off (asked again with --yes)").add_argument(
        "--yes", action="store_true", help="what it has not written is lost: go on anyway")
    machine("autostart", "turn a machine's autostart on or off").add_argument("on", choices=("on", "off"))
    s = machine("snapshot", "take a snapshot of a machine")
    s.add_argument("snapshot", nargs="?")
    s.add_argument("--description")
    r = machine("revert", "revert a machine to a snapshot (asked again with --yes)")
    r.add_argument("snapshot")
    r.add_argument("--yes", action="store_true", help="what changed since the snapshot is lost: go on anyway")
    v = sub.add_parser("service", help="start one of libvirt's services")
    v.add_argument("unit")
    v.add_argument("action", choices=("start",))
    x = sub.add_parser("run", help="virsh on a connection with these arguments")
    x.add_argument("--session", action="store_true")
    x.add_argument("args", nargs=argparse.REMAINDER)
    return p


def said(answer: dict) -> int:
    print(answer.get("said", "done"))
    for line in answer.get("lines") or []:
        print(f"  {line}")
    return 0 if answer.get("ok", True) else 1


def main(argv: list[str] | None = None, machine=None) -> int:
    m = machine if machine is not None else MACHINE
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["status"]
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:  # argparse's own usage message is printed
        return 2 if e.code else 0
    where = "session" if getattr(args, "session", False) else "system"
    try:
        if args.what == "status":
            if args.wake:
                m.wake()
            st = m.status()
            print(json.dumps(st, indent=1))
            return 0 if st.get("valid") else 1
        if args.what == "wake":
            return said(m.wake())
        if args.what in ("start", "shutdown", "reboot"):
            return said(m.power(args.name, args.what, where))
        if args.what == "destroy":
            return said(m.power(args.name, "destroy", where, accept_destroy=args.yes))
        if args.what == "autostart":
            return said(m.autostart(args.name, args.on, where))
        if args.what == "snapshot":
            return said(m.snapshot(args.name, args.snapshot, args.description, where))
        if args.what == "revert":
            return said(m.revert(args.name, args.snapshot, where, accept_revert=args.yes))
        if args.what == "service":
            return said(m.service(args.unit, args.action))
        if args.what == "run":
            rest = args.args[1:] if args.args[:1] == ["--"] else args.args
            if rest:
                print(m.run(*rest, connection=where), end="")
                return 0
    except Refusal as e:
        print(f"refused: {e}" + (" (again with --yes to go on)" if e.accept else ""), file=sys.stderr)
        return 1
    except CommandError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
