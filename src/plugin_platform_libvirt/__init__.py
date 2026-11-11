"""libvirt for Liminal (the user, 2026-11-08: "LXC/LXD plugins and LIBVIRT plugin for virtualization"; of the Linux
plugins: "make sure its compatable with systemd/openrc ... make sure its compatible with major distributions and gentoo
linux"): the virtual machines libvirt runs with QEMU/KVM on the native Linux machine the platform runs on, and nowhere
else (the user: "the scope of linux administration is only on native linux O/S"; "it's not for administrating WSL
instances"): on Windows, on macOS and inside a WSL distribution it runs no command at all (the library's
machines.linux.why_not_native), asks nothing and offers no setup.

Read through virsh on both connections, qemu:///system (root's daemon) and qemu:///session (the platform's user's
own): the domains (`virsh list --all`, each one's dominfo: state, vCPUs, memory, autostart), their snapshots, the
networks (`net-list --all`) and the storage pools (`pool-list --all --details`); KVM's presence (/dev/kvm, kvm_intel or
kvm_amd, the processor's vmx or svm). Changed only when asked, through the platform page's confirmed forms or this
command line: a machine started, shut down (ACPI) or rebooted; forced off (`virsh destroy`) only once asked a second
time (accept); its autostart turned on or off; a snapshot taken; a snapshot reverted to, asked a second time. libvirt's
services, the monolithic libvirtd or the modular virtqemud, virtnetworkd and virtstoraged (with virtlogd, virtlockd and
libvirt-guests), under systemd, OpenRC (Gentoo's app-emulation/libvirt) or SysV scripts, are shown and started only
when asked; none is ever stopped. Nothing is started by a read either: a daemon that is idle (systemd's socket
listening, the daemon not running) and the session's own daemon (virsh would start one) are read once the user asks
(Read now).

qemu:///system's commands run as the platform's user when it is in the libvirt group (libvirt's polkit rule lets its
members manage the system's machines), plainly when the platform is root, else as root through the library's
linux.Shell (sudo -n, never a password asked); when none of that works the status says how to give the rights.
qemu:///session's are always the user's own.

    python -m plugin_platform_libvirt status [--wake] | wake | start|shutdown|reboot NAME [--session]
        | destroy NAME [--session] [--yes] | autostart NAME on|off [--session]
        | snapshot NAME [SNAPSHOT] [--description TEXT] [--session] | revert NAME SNAPSHOT [--session] [--yes]
        | service UNIT start | run [--session] -- ARGS...
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from liminal_libs.machines import linux
from liminal_libs.machines.linux import Shell
from liminal_libs.machines.plugin import CommandError, MachinePlugin

from . import apis as cards
from .inventory import ACTIVE, URIS, Connection, parse as parse_read, read_script, words_of
from .system import (GROUPS, PROBE, Probe, distribution, family, init_words, install_words, kvm_words, parse as parse_probe)

__version__ = "0.2.0"
SUDO_S = 300.0  # sudo -n's answer kept this long: a refusal is logged by sudo each time it is asked
POWER = ("start", "shutdown", "reboot", "destroy")
DONE = {"start": "started", "shutdown": "asked to shut down", "reboot": "asked to reboot", "destroy": "forced off"}
CHANGE_S = 120.0
SNAPSHOT_S = 900.0  # a running machine's memory is written with its snapshot
READ_S = 120.0
SERVICE_S = 120.0
SNAPSHOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._-]{0,127}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
DENIED = ("permission denied", "authentication unavailable", "authentication failed", "not authorized", "polkit",
          "a password is required", "access denied")
# each part of qemu:///system and the daemon serving it: libvirtd alone, or the modular daemons
PART_DAEMON = {"modular": {"domains": "virtqemud", "networks": "virtnetworkd", "pools": "virtstoraged"},
               "monolithic": {"domains": "libvirtd", "networks": "libvirtd", "pools": "libvirtd"}}
PART_WORDS = {"domains": "the machines", "networks": "the networks", "pools": "the storage pools"}


class LibvirtError(CommandError):
    """libvirt refused or failed, in words; `denied`: for want of the rights."""


class Refusal(ValueError):
    """A change not made, and why: nothing ran. `accept`: the argument that, set, makes it anyway (the platform's page
    asks it as a second, explicit confirmation; the command line's --yes)."""

    def __init__(self, message: str, accept: str | None = None):
        super().__init__(message)
        self.accept = accept


def why_not_native(system: str | None = None, release: str | None = None, env=None) -> str:
    """Why the machine the platform runs on is not a native Linux one, in words ("" when it is): the library's check
    (liminal-libs 1.27.0, shared with the Linux administration and firewall plugins)."""
    return linux.why_not_native("libvirt", system, release, env)


def yes(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1", "on")


def given(value) -> bool:
    return value is not None and str(value).strip() != ""


def onoff(value) -> bool:
    text = str(value).strip().lower() if value is not None else ""
    if value is True or text in ("on", "yes", "true", "1", "enable"):
        return True
    if value is False or text in ("off", "no", "false", "0", "disable"):
        return False
    raise Refusal(f"{value!r} is neither on nor off")


def connection_of(value) -> str:
    c = str(value or "system").strip().lower()
    c = {"qemu:///system": "system", "qemu:///session": "session"}.get(c, c)
    if c not in URIS:
        raise Refusal(f"{value!r} is neither qemu:///system nor qemu:///session")
    return c


def domain_name(value) -> str:
    name = str(value if value is not None else "")
    if not name.strip() or len(name) > 200 or CONTROL.search(name):
        raise Refusal(f"{name!r} is not a virtual machine's name")
    return name


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def memory(kib: int | None) -> str:
    if kib is None:
        return "–"
    mib = kib / 1024
    return f"{mib / 1024:.1f} GiB" if mib >= 1024 else f"{mib:.0f} MiB"


def cell(text, sub: str | None = None):
    return {"text": text, "sub": sub} if sub else text


def answer(said: str, out: str = "", ok: bool = True) -> dict:
    return {"said": said, "lines": [line.strip() for line in (out or "").splitlines() if line.strip()][:20], "ok": ok}


def mode_of(p: Probe) -> str:
    """modular (virtqemud and its siblings) or monolithic (libvirtd), as this machine runs libvirt: what is running or
    set to start; else what the distribution ships by default (Fedora, RHEL and openSUSE: modular)."""
    def on(name: str) -> bool:
        units = [u for u in p.units.values() if u.name.split(".")[0] == name]
        return any(u.up or u.enabled for u in units)

    def loaded(name: str) -> bool:
        return any(u.name.split(".")[0] == name for u in p.units.values())
    system_daemons, system_sockets = p.daemons.get("system", frozenset()), p.sockets.get("system", frozenset())
    if "virtqemud" in system_daemons or "virtqemud-sock" in system_sockets or on("virtqemud"):
        return "modular"
    if "libvirtd" in system_daemons or on("libvirtd"):
        return "monolithic"
    if loaded("virtqemud") and family(p.os) in ("fedora", "rhel", "opensuse"):
        return "modular"
    if loaded("libvirtd"):
        return "monolithic"
    return "modular" if loaded("virtqemud") else "monolithic"


def part_state(p: Probe, mode: str, part: str) -> tuple[str, str]:
    """A part of qemu:///system: running (its daemon runs) | idle (its socket listens: the first client starts it) |
    stopped; and its daemon or socket."""
    daemon = PART_DAEMON[mode][part]
    if daemon in p.daemons.get("system", frozenset()) or any(u.state == "running" for u in p.units.values() if u.name in (daemon, f"{daemon}.service")):
        return "running", daemon
    socket = "libvirt-sock" if daemon == "libvirtd" else f"{daemon}-sock"
    if socket in p.sockets.get("system", frozenset()) or any(u.state == "listening" for u in p.units.values() if u.name == f"{daemon}.socket"):
        return "idle", f"{daemon}.socket" if p.init == "systemd" else socket
    return "stopped", daemon


def session_state(p: Probe) -> tuple[str, str]:
    """qemu:///session: root (the platform is root: no user's session) | running | idle (systemd's user socket
    listens) | none (no session daemon: virsh would start one)."""
    if p.root:
        return "root", ""
    up = sorted(p.daemons.get("session", frozenset()))
    if up:
        return "running", up[0]
    sockets = sorted(p.sockets.get("session", frozenset()))
    return ("idle", sockets[0]) if sockets else ("none", "")


@dataclass(frozen=True)
class Access:
    """How qemu:///system's commands run: `kind` root | group | sudo | none; `as_root` through sudo -n; `words`."""
    kind: str
    as_root: bool
    words: str
    how: str = ""


def access_of(p: Probe, sudo) -> Access:
    """The rights the platform has over qemu:///system; `sudo()` asks whether sudo -n works (only when it matters)."""
    user = p.user or "the platform's user"
    how = (f"add {user} to libvirt (sudo usermod -aG libvirt {user}) and log in again, so the platform runs with the group; "
           f"or run the platform as root; or let sudo run commands for {user} without a password")
    if p.root:
        return Access("root", False, "the platform runs as root", how)
    group = next((g for g in GROUPS if g in p.groups), None)
    if group:
        return Access("group", False, f"{user} is in {group}: qemu:///system as {user}, no sudo", how)
    later = any(g in p.member for g in GROUPS)
    after = f"; {user} was added to libvirt after this login: started from a new login, the platform needs no sudo" if later else ""
    if sudo():
        return Access("sudo", True, f"{user} is not in libvirt: qemu:///system as root through sudo -n{after}", how)
    if later:
        return Access("none", True, f"{user} was added to libvirt after this login, and sudo asks for a password: log in again "
                                    "and start the platform from that login, so it runs with the group", how)
    return Access("none", True, f"{user} is neither root nor in libvirt, and sudo asks for a password: {how}", how)


@dataclass(frozen=True)
class Context:
    """One look at this machine: its probe, libvirt's mode, the rights over qemu:///system, each part's state."""
    shell: Shell
    probe: Probe
    mode: str = "monolithic"
    access: Access | None = None
    parts: tuple = ()  # ((part, state, by), ...) of qemu:///system
    session: tuple = ("none", "")

    @property
    def virsh(self) -> str:
        return self.probe.virsh or "virsh"

    def part(self, name: str) -> tuple[str, str]:
        return next(((s, b) for p, s, b in self.parts if p == name), ("stopped", ""))


def start_command(init: str, unit: str) -> list[str]:
    if init == "openrc":
        return ["rc-service", unit, "start"]
    if init == "sysvinit":
        return ["service", unit, "start"]
    return ["systemctl", "start", unit]


class LibvirtPlugin(MachinePlugin):
    """libvirt's virtual machines on this native Linux machine: read, and changed only when asked."""

    name = "libvirt"
    title = "libvirt"
    about = ("libvirt's virtual machines (QEMU/KVM) on the native Linux machine the platform runs on, never a WSL "
             "distribution: qemu:///system's and the user's qemu:///session's, their snapshots, the networks, the storage "
             "pools, KVM and libvirt's services; changed only when asked")
    api = "2.2"
    # what it attaches to (plugin API 2.2): virsh and the libvirt API under it, libvirt's daemons and services, KVM
    # (apis.py: each one's pages, parts and calls)
    apis = cards.APIS
    order = 706  # the machine's own instances: WSL's on Windows (700-702), LXC / LXD and libvirt on Linux
    ICON = "libvirt"  # its logo's tin of penguins, the lid rolled back on its key (liminal-libs 1.34.0)
    HOOKS = (*MachinePlugin.HOOKS, "power", "autostart", "snapshot", "revert", "service", "wake")

    def __init__(self, shell: Shell | None = None, runner=None, native: str | None = None):
        self._shell = shell
        self._runner = runner
        self._native = native  # a test's word for why_not_native(): "" on a native Linux machine, else why not
        self._woken = False  # idle daemons and the session read once asked (Read now), until the platform lets it go
        self._sudo: tuple[float, bool] | None = None  # (when, whether sudo -n ran without a password)
        # what the last look and read said (api_facts, plugin API 2.2): kept in one dict its copies share, asked nothing
        self._learned: dict = {}

    def not_for_here(self) -> str:
        return why_not_native() if self._native is None else self._native

    @property
    def shell(self) -> Shell:
        """This native Linux machine's commands (root through sudo -n); refused anywhere else, and for a WSL target."""
        note = self.not_for_here()
        if note:
            raise LibvirtError(note)
        sh = self._shell if self._shell is not None else Shell("local", runner=self._runner)
        if sh.target != "local":
            raise LibvirtError(f"libvirt is for this native Linux machine, never {sh.where}")
        return sh

    def detach(self) -> None:
        """Let go by the platform: idle daemons and the session are no longer read until asked again; what was learned
        goes too."""
        self._woken = False
        self._learned.clear()
        super().detach()

    def _remember(self, ctx: Context, read: tuple = ()) -> None:
        """What a look (and a read of its connections) said, kept for api_facts: no request of its own."""
        p = ctx.probe
        seen = {"at": time.time(), "virsh": p.virsh, "version": p.version, "kvm": kvm_words(p)[0], "init": init_words(p),
                "distribution": distribution(p), "units": {u.name: u.state for u in p.units.values() if u.known}}
        if p.virsh:
            seen.update(mode=self._mode_words(ctx), system=self._system_words(ctx), session=self._session_words(ctx),
                        rights=ctx.access.words if ctx.access else "", sudo=self._sudo)
        for c in read:
            seen[f"read {c.name}"] = ({"domains": len(c.domains), "running": sum(d.running for d in c.domains),
                                       "snapshots": len(c.snapshots), "networks": len(c.networks), "pools": len(c.pools),
                                       "problems": list(c.problems)} if c.read else None)
        self._learned.update(seen)

    def api_facts(self) -> dict:
        """What it learned of its APIs while it ran (plugin API 2.2), asking nothing: virsh and its version, what each
        connection's last read held and its troubles; the daemons (monolithic or modular, each part's state), the rights
        and whether sudo -n answered, the init system, the services; KVM as the last look found it. Nothing looked at yet:
        {}."""
        seen = dict(self._learned)
        if not seen:
            return {}
        when = time.strftime("%b %d %H:%M:%S", time.localtime(seen["at"]))
        out: dict[str, dict[str, str]] = {}
        if seen.get("virsh"):
            virsh = {"Looked at": when, "virsh": f"{seen['virsh']} ({seen.get('version') or 'its version not said'})"}
            for name in ("system", "session"):
                read = seen.get(f"read {name}")
                if read:
                    virsh[f"qemu:///{name}"] = (f"{read['domains']} machines ({read['running']} running), "
                                                f"{read['snapshots']} snapshots" + (
                                                    f", {read['networks']} networks, {read['pools']} pools" if name == "system" else ""))
                    if read["problems"]:
                        virsh[f"qemu:///{name}: trouble"] = "; ".join(read["problems"])[:200]
            out[cards.VIRSH] = virsh
        daemons = {"Looked at": when, "Init system": seen["init"], "Distribution": seen["distribution"]}
        if seen.get("virsh"):
            daemons.update({"Daemons": seen["mode"], "qemu:///system": seen["system"], "qemu:///session": seen["session"],
                            "Rights": seen["rights"]})
        if seen.get("units"):
            daemons["Services"] = ", ".join(f"{n} {s}" for n, s in sorted(seen["units"].items()))
        sudo = self._sudo or seen.get("sudo")
        if sudo:
            daemons["sudo -n"] = "answers without a password" if sudo[1] else "asks a password: not used"
        out[cards.DAEMONS] = daemons
        out[cards.KVM] = {"Looked at": when, "KVM": seen["kvm"]}
        return out

    # -- looking --------------------------------------------------------------------------------------------------
    def _probe(self, sh: Shell) -> Probe:
        found = parse_probe(sh.sh(PROBE, root=False, timeout=60))
        if found.problem:
            raise LibvirtError(found.problem)
        return found

    def _context(self) -> Context:
        sh = self.shell
        p = self._probe(sh)
        if not p.virsh:
            ctx = Context(sh, p)
            self._remember(ctx)
            return ctx
        mode = mode_of(p)

        def sudo() -> bool:
            now = time.monotonic()
            if self._sudo is None or now - self._sudo[0] > SUDO_S:
                try:
                    sh.run("true", timeout=30)  # sudo -n true: never a password asked
                    self._sudo = (now, True)
                except CommandError:
                    self._sudo = (now, False)
            return self._sudo[1]
        parts = tuple((part, *part_state(p, mode, part)) for part in PART_DAEMON[mode])
        ctx = Context(sh, p, mode, access_of(p, sudo), parts, session_state(p))
        self._remember(ctx)
        return ctx

    def _ready(self) -> Context:
        ctx = self._context()
        if not ctx.probe.virsh:
            raise LibvirtError(install_words(ctx.probe))
        return ctx

    def _root(self, ctx: Context, connection: str) -> bool:
        return connection == "system" and ctx.access.as_root

    def _run(self, ctx: Context, connection: str, *args: str, timeout: float = CHANGE_S) -> str:
        """virsh on a connection with the platform's rights over it; a refusal for want of them says how they are given."""
        if connection == "system" and ctx.access.kind == "none":
            raise LibvirtError(ctx.access.words, denied=True)
        if connection == "session" and ctx.probe.root:
            raise Refusal("the platform runs as root: qemu:///session would be root's own, not a user's; use qemu:///system")
        try:
            return ctx.shell.run(ctx.virsh, "-c", URIS[connection], *args, root=self._root(ctx, connection), timeout=timeout)
        except CommandError as e:
            text = words_of([str(e)])
            if connection == "system" and (e.denied or any(d in text.lower() for d in DENIED)):
                raise LibvirtError(f"{text}; {ctx.access.how}", denied=True) from None
            raise LibvirtError(text) from None

    def _read(self, ctx: Context, connection: str, parts) -> Connection:
        if not parts:
            return Connection(connection, read=False)
        script = read_script(ctx.virsh, connection, parts)
        try:
            return parse_read(ctx.shell.sh(script, root=self._root(ctx, connection), timeout=READ_S), connection)
        except CommandError as e:  # the read itself refused (sudo -n for sh, a timeout): said, never raised
            return Connection(connection, problems=[str(e)], denied=e.denied)

    def _system_parts(self, ctx: Context) -> tuple:
        """The parts of qemu:///system read now: those whose daemon runs, the idle ones once asked."""
        if ctx.access.kind == "none":
            return ()
        return tuple(part for part, state, _ in ctx.parts if state == "running" or (state == "idle" and self._woken))

    def _session_read(self, ctx: Context) -> bool:
        state = ctx.session[0]
        return state == "running" or (state in ("idle", "none") and self._woken)

    def present(self) -> bool:
        """virsh installed on a native Linux machine: never on Windows, macOS or in WSL."""
        if self.not_for_here():
            return False
        try:
            return bool(self._probe(self.shell).virsh)
        except CommandError:
            return False

    # -- the status -----------------------------------------------------------------------------------------------
    def status(self) -> dict:
        note = self.not_for_here()
        if note:  # not for this machine at all: asked nothing, no setup offered
            return self.not_here_status(note, tables=[], forms=[], actions=[])
        try:
            ctx = self._context()
        except CommandError as e:
            return {"present": False, "summary": f"cannot be read: {e}", "valid": False, "why": f"cannot be read: {e}",
                    "tables": [], "forms": [], "actions": []}
        p = ctx.probe
        kvm, has_kvm = kvm_words(p)
        if not p.virsh:
            return {"present": False, "summary": "not installed", "kvm": kvm, "distribution": distribution(p),
                    "initSystem": init_words(p), "valid": False, "why": install_words(p), "tables": [], "forms": [], "actions": []}
        soft = f"libvirt {p.version} (virsh)" if p.version else "libvirt (virsh)"
        system = self._read(ctx, "system", self._system_parts(ctx))
        session = self._read(ctx, "session", ("domains",)) if self._session_read(ctx) else Connection("session", read=False)
        self._remember(ctx, (system, session))
        facts = {"software": soft, "daemons": self._mode_words(ctx), "system": self._system_words(ctx),
                 "session": self._session_words(ctx), "kvm": kvm, "rights": ctx.access.words + (
                     "; qemu:///session as the user always" if not p.root else ""),
                 "initSystem": init_words(p), "distribution": distribution(p)}
        domains = system.domains + session.domains
        if system.read or session.read:
            on = [c for c in (system, session) if c.read and not (c.problems and not c.domains)]
            up = sum(d.running for d in domains)
            facts["machines"] = f"{len(domains)}: {up} running" + (" · " + ", ".join(f"{len(c.domains)} on {c.uri}" for c in on) if on else "")
            facts["snapshots"] = str(len(system.snapshots) + len(session.snapshots))
        if system.networks:
            facts["networks"] = ", ".join(f"{n.name} ({n.state})" for n in system.networks)
        if system.pools:
            facts["storagePools"] = ", ".join(f"{po.name} ({po.state}" + (f", {po.available} free" if po.available != "-" else "") + ")"
                                              for po in system.pools)
        problems = []
        if ctx.access.kind == "none":
            problems.append(f"qemu:///system is not read: {ctx.access.words}")
        stopped = [by for part, state, by in ctx.parts if state == "stopped"]
        if stopped and ctx.access.kind != "none":
            problems.append(f"libvirt's {', '.join(dict.fromkeys(stopped))} {'is' if len(set(stopped)) == 1 else 'are'} stopped: "
                            "Start… under Daemons starts it")
        for c in (system, session):
            problems += [f"{c.uri}: {w}" for w in c.problems]
            if c.denied and c.name == "system":
                problems.append(ctx.access.how)
        if not has_kvm:
            problems.append(kvm)
        tables = [self._machines_table(ctx, system, session), self._snapshots_table(system, session)]
        if system.read and "networks" in self._system_parts(ctx):
            tables.append(self._networks_table(system))
        if system.read and "pools" in self._system_parts(ctx):
            tables.append(self._pools_table(system))
        tables.append(self._daemons_table(ctx))
        idle = (any(state == "idle" for _, state, _ in ctx.parts) and ctx.access.kind != "none") or ctx.session[0] in ("idle", "none")
        out = {"present": True, "summary": self._summary(ctx, soft, system, session), **facts, "valid": True, "why": "",
               "tables": tables, "forms": self._forms(ctx),
               "actions": [{"form": "wake", "title": "Read now…", "note": "connects to libvirt's idle daemons, which starts them"}]
               if idle and not self._woken else []}
        if problems:
            out["problem"] = "; ".join(problems)
        return out

    @staticmethod
    def _mode_words(ctx: Context) -> str:
        if ctx.mode == "modular":
            return "modular: virtqemud, virtnetworkd, virtstoraged" + (" (systemd's sockets start them)" if ctx.probe.init == "systemd" else "")
        return "monolithic: libvirtd"

    @staticmethod
    def _system_words(ctx: Context) -> str:
        """qemu:///system's daemons by their state: "running (virtqemud, virtnetworkd)", "idle: virtstoraged.socket
        listens ...", "stopped (libvirtd): ..."."""
        by_state: dict[str, list[str]] = {}
        for _, state, by in ctx.parts:
            names = by_state.setdefault(state, [])
            if by not in names:
                names.append(by)
        words = []
        for state in ("running", "idle", "stopped"):
            names = by_state.get(state)
            if not names:
                continue
            one = len(names) == 1
            if state == "running":
                words.append(f"running ({', '.join(names)})")
            elif state == "idle":
                words.append(f"idle: {', '.join(names)} {'listens and starts its daemon' if one else 'listen and start their daemons'} "
                             "for the first client; read when asked (Read now)")
            else:
                words.append(f"stopped ({', '.join(names)}): Start… under Daemons starts {'it' if one else 'them'}")
        return "qemu:///system " + "; ".join(words)

    @staticmethod
    def _session_words(ctx: Context) -> str:
        state, by = ctx.session
        user = ctx.probe.user or "the user"
        if state == "root":
            return "qemu:///session not read: the platform runs as root, so it would be root's own"
        if state == "running":
            return f"qemu:///session running ({user}'s {by})"
        if state == "idle":
            return f"qemu:///session idle: {by} listens for {user}; read when asked (Read now)"
        return f"qemu:///session: no session daemon running for {user}, and virsh would start one; read when asked (Read now)"

    def _summary(self, ctx: Context, soft: str, system: Connection, session: Connection) -> str:
        if not (system.read or session.read):
            if ctx.access.kind == "none":
                return f"{soft}: qemu:///system needs rights"
            if all(state == "stopped" for _, state, _ in ctx.parts):
                return f"{soft}: libvirt's daemon is stopped"
            return f"{soft}: libvirt's daemon is idle (Read now… reads it)"
        domains = system.domains + session.domains
        if not domains and (system.problems or session.problems):
            return f"{soft}: {(system.problems or session.problems)[0]}"
        up = sum(d.running for d in domains)
        return f"{soft}: {plural(len(domains), 'virtual machine')}, {up} running" if domains else f"{soft}: no virtual machines yet"

    # -- the tables -----------------------------------------------------------------------------------------------
    @staticmethod
    def _machines_table(ctx: Context, system: Connection, session: Connection) -> dict:
        rows = []
        for d in system.domains + session.domains:
            values = {"name": d.name, "connection": d.connection}
            sub = " · ".join(x for x in (d.connection != "system" and URIS[d.connection], d.persistent is False and "transient") if x) or None
            running = d.state in ACTIVE
            power = {"form": "power", "title": "Shut down…" if running else "Start…",
                     "values": {**values, "action": "shutdown" if running else "start"},
                     "label": f"Start, shut down, reboot or force off {d.name}"}
            if d.persistent is False or d.autostart is None:
                auto = cell("–", "transient" if d.persistent is False else None)
            else:
                auto = {"form": "autostart", "title": "on" if d.autostart else "off", "values": {**values, "on": "off" if d.autostart else "on"},
                        "label": f"Turn autostart {'off' if d.autostart else 'on'} for {d.name}"}
            mem = cell(memory(d.memory), f"of {memory(d.max_memory)} at most" if d.max_memory and d.memory and d.max_memory > d.memory else None)
            snap = {"form": "snapshot", "title": "Snapshot…", "values": values, "label": f"Take a snapshot of {d.name}"}
            rows.append([cell(d.name, sub), d.state, "–" if d.vcpus is None else str(d.vcpus), mem, auto, power, snap])
        reasons = []
        if not system.read:
            if ctx.access.kind == "none":
                reasons.append(f"qemu:///system needs rights ({ctx.access.words})")
            else:
                state, by = ctx.part("domains")
                reasons.append(f"qemu:///system is idle ({by} listens): Read now… reads it" if state == "idle" else
                               f"qemu:///system's {by} is stopped: Start… under Daemons starts it")
        if not session.read and ctx.session[0] in ("idle", "none"):
            reasons.append("qemu:///session has no daemon running: Read now… reads it, which starts the user's own")
        elif not session.read and ctx.session[0] == "root":
            reasons.append("qemu:///session is not read: the platform runs as root")
        problems = [f"{c.uri}: {c.problems[0]}" for c in (system, session) if c.read and c.problems and not c.domains]
        empty = ("Not read: " + "; ".join(reasons + problems) + ".") if reasons or problems else \
            "No virtual machines yet: virt-install or virt-manager makes one."
        return {"title": "Virtual machines",
                "note": "a shut down asks the machine's own system (ACPI) and may be ignored; Force off cuts its power, asked twice",
                "columns": [{"title": "Machine"}, {"title": "State"}, {"title": "vCPUs", "num": True}, {"title": "Memory", "num": True},
                            {"title": "Autostart"}, {"title": ""}, {"title": ""}], "rows": rows, "empty": empty}

    @staticmethod
    def _snapshots_table(system: Connection, session: Connection) -> dict:
        rows = []
        for s in system.snapshots + session.snapshots:
            values = {"name": s.domain, "snapshot": s.name, "connection": s.connection}
            rows.append([cell(s.domain, URIS[s.connection] if s.connection != "system" else None), s.name, s.created or "–", s.state or "–",
                         {"form": "revert", "title": "Revert…", "values": values, "label": f"Revert {s.domain} to {s.name}"}])
        return {"title": "Snapshots", "columns": [{"title": "Machine"}, {"title": "Snapshot"}, {"title": "Taken"}, {"title": "Then"},
                                                  {"title": ""}],
                "rows": rows, "empty": "No snapshots: Snapshot… beside a machine takes one."}

    @staticmethod
    def _networks_table(system: Connection) -> dict:
        rows = [[n.name, n.state, "yes" if n.autostart else "no", "yes" if n.persistent else "no"] for n in system.networks]
        return {"title": "Networks", "note": "qemu:///system's", "columns": [{"title": "Network"}, {"title": "State"},
                                                                             {"title": "Autostart"}, {"title": "Persistent"}],
                "rows": rows, "empty": "No networks: libvirt's default one (virbr0) comes with its network driver."}

    @staticmethod
    def _pools_table(system: Connection) -> dict:
        rows = [[po.name, po.state, "yes" if po.autostart else "no", po.capacity, po.allocation, po.available] for po in system.pools]
        return {"title": "Storage pools", "note": "qemu:///system's",
                "columns": [{"title": "Pool"}, {"title": "State"}, {"title": "Autostart"}, {"title": "Capacity", "num": True},
                            {"title": "Allocation", "num": True}, {"title": "Available", "num": True}],
                "rows": rows, "empty": "No storage pools: virt-manager or virsh pool-define-as makes one (default: /var/lib/libvirt/images)."}

    @staticmethod
    def _daemons_table(ctx: Context) -> dict:
        p = ctx.probe
        units = sorted((u for u in p.units.values() if u.known and u.known.mode in (ctx.mode, "*")),
                       key=lambda u: (not u.known.daemon, u.known.mode == "*", u.name))
        rows = [[u.name, u.state, u.boot or "–", u.role,
                 {"form": "service", "title": "Start…", "values": {"unit": u.name, "action": "start"}, "label": f"Start {u.name}"}
                 if u.startable else ""] for u in units]
        return {"title": "Daemons", "note": f"{init_words(p)}; libvirt {ctx.mode}; a service is started here only when asked, and never stopped",
                "columns": [{"title": "Service"}, {"title": "State"}, {"title": "At boot"}, {"title": "What it is"}, {"title": ""}],
                "rows": rows, "empty": f"None of libvirt's services is known to {init_words(p)} here."}

    # -- the forms (the platform's page: each change confirmed; forcing off and reverting asked a second time) -----
    def _forms(self, ctx: Context) -> list[dict]:
        name = {"name": "name", "label": "Machine", "type": "fixed"}
        connection = {"name": "connection", "label": "Connection", "type": "fixed", "value": "system",
                      "choices": [{"value": "system", "title": "qemu:///system"}, {"value": "session", "title": "qemu:///session (the user's own)"}]}
        power = {"id": "power", "hook": "power", "title": "Start, shut down, reboot or force off a machine",
                 "fields": [name, {"name": "action", "label": "Do", "type": "choice", "value": "start", "choices": [
                     {"value": "start", "title": "Start", "note": "boots it"},
                     {"value": "shutdown", "title": "Shut down", "note": "asks its own system to shut down (ACPI): it may take a while, or be ignored"},
                     {"value": "reboot", "title": "Reboot", "note": "asks its own system to reboot"},
                     {"value": "destroy", "title": "Force off", "note": "cuts its power at once (virsh destroy): asked a second time"}]},
                            connection,
                            {"name": "accept_destroy", "type": "accept", "title": "Force it off?", "yes": "Force it off",
                             "words": "{name} loses its power at once, as when a plug is pulled: what it has not written to its disks is "
                                      "lost, and its file systems may need a check."}],
                 "submit": "Review",
                 "confirm": {"title": "{action} {name}?", "words": "Asked of libvirt now on {connection}; nothing else changes.", "yes": "Yes, do it"}}
        autostart = {"id": "autostart", "hook": "autostart", "title": "Autostart",
                     "fields": [name, {"name": "on", "label": "Autostart", "type": "choice", "value": "on", "choices": [
                         {"value": "on", "title": "on", "note": "started whenever libvirt's daemon starts (at boot, when it is set to)"},
                         {"value": "off", "title": "off", "note": "started only when asked"}]}, connection],
                     "submit": "Review",
                     "confirm": {"title": "Turn autostart {on} for {name}?", "words": "virsh autostart on {connection}; the machine itself is left as it is.",
                                 "yes": "Yes, do it"}}
        snapshot = {"id": "snapshot", "hook": "snapshot", "title": "Take a snapshot of a machine",
                    "fields": [name, {"name": "snapshot", "label": "Its name", "type": "text", "placeholder": "before-update",
                                      "note": "letters, digits, dots, dashes, underscores; empty: libvirt names it by the time"},
                               {"name": "description", "label": "Description", "type": "text", "placeholder": "what it is before"},
                               connection],
                    "submit": "Review",
                    "confirm": {"title": "Take a snapshot of {name}?",
                                "words": ("virsh snapshot-create-as --atomic: its disks as they are now, and a running machine's memory. "
                                          "A machine whose firmware is UEFI may be refused by libvirt before 9.9 (its internal "
                                          "snapshots need BIOS firmware)."),
                                "yes": "Take it"}}
        revert = {"id": "revert", "hook": "revert", "title": "Revert a machine to a snapshot",
                  "fields": [name, {"name": "snapshot", "label": "Snapshot", "type": "fixed"}, connection,
                             {"name": "accept_revert", "type": "accept", "title": "Lose what changed since the snapshot?", "yes": "Revert it",
                              "words": "{name}'s disks (and its memory, for a snapshot of a running machine) are replaced by {snapshot}'s: "
                                       "whatever changed since is lost for good. A snapshot taken first keeps it."}],
                  "confirm": {"title": "Revert {name} to {snapshot}?",
                              "words": "{name} is put back as it was when {snapshot} was taken: running if it was running then.",
                              "yes": "Revert", "danger": True}}
        how = {"openrc": "rc-service {unit} start", "sysvinit": "service {unit} start"}.get(ctx.probe.init, "systemctl start {unit}")
        service = {"id": "service", "hook": "service", "title": "Start a service",
                   "fields": [{"name": "unit", "label": "Service", "type": "fixed"}, {"name": "action", "label": "Do", "type": "fixed", "value": "start"}],
                   "confirm": {"title": "Start {unit}?", "words": f"{how}, as root (sudo -n when the platform is not root). "
                                                                  "Whether it starts at boot is left as it is.", "yes": "Start it"}}
        wake = {"id": "wake", "hook": "wake", "title": "Read now", "fields": [],
                "confirm": {"title": "Read libvirt now?",
                            "words": ("Reading connects to libvirt's idle daemons, which starts them: systemd's sockets start "
                                      "qemu:///system's, and the user's own session daemon is started for qemu:///session. They "
                                      "stop again after two idle minutes; the plugin reads them from now on, until the platform "
                                      "lets it go."),
                            "yes": "Read now"}}
        return [power, autostart, snapshot, revert, service, wake]

    # -- the hooks: changes, each asked ---------------------------------------------------------------------------
    def _domain(self, ctx: Context, connection: str, name: str, active: bool = False) -> bool:
        """Whether `name` is one of the connection's machines (refused when it is not); `active`: also whether it runs."""
        names = self._run(ctx, connection, "list", "--all", "--name", timeout=READ_S).splitlines()
        if name not in [n for n in names if n]:
            raise Refusal(f"no virtual machine named {name} on {URIS[connection]}")
        if not active:
            return False
        return name in self._run(ctx, connection, "list", "--name", timeout=READ_S).splitlines()

    def power(self, name, action, connection="system", accept_destroy=False) -> dict:
        """Start, shut down (ACPI: the machine's own system is asked), reboot, or force off (asked twice)."""
        act = str(action or "").strip().lower()
        if act not in POWER:
            raise Refusal(f"{act!r} is none of {', '.join(POWER)}")
        name, c = domain_name(name), connection_of(connection)
        ctx = self._ready()
        running = self._domain(ctx, c, name, active=act == "destroy")
        if act == "destroy":
            if not running:
                raise Refusal(f"{name} is not running: nothing to force off")
            if not yes(accept_destroy):
                raise Refusal(f"forcing {name} off cuts its power at once: what it has not written to its disks is lost",
                              accept="accept_destroy")
        return answer(f"{name}: {DONE[act]}", self._run(ctx, c, act, "--domain", name))

    def autostart(self, name, on, connection="system") -> dict:
        """A machine started whenever libvirt's daemon starts, or not."""
        turn = onoff(on)
        name, c = domain_name(name), connection_of(connection)
        ctx = self._ready()
        self._domain(ctx, c, name)
        out = self._run(ctx, c, "autostart", "--domain", name, *([] if turn else ["--disable"]))
        return answer(f"{name}: autostart {'on' if turn else 'off'}", out)

    def snapshot(self, name, snapshot=None, description=None, connection="system") -> dict:
        """A snapshot taken now (virsh snapshot-create-as --atomic): named, or named by libvirt."""
        name, c = domain_name(name), connection_of(connection)
        snap = str(snapshot).strip() if given(snapshot) else None
        if snap and not SNAPSHOT.match(snap):
            raise Refusal(f"{snap!r} is not a snapshot's name: letters, digits, dots, dashes and underscores, at most 63")
        text = str(description).strip() if given(description) else None
        if text and (len(text) > 200 or CONTROL.search(text)):
            raise Refusal("a description is one line of at most 200 characters")
        ctx = self._ready()
        self._domain(ctx, c, name)
        args = ["snapshot-create-as", "--domain", name, *(["--name", snap] if snap else []),
                *(["--description", text] if text else []), "--atomic"]
        return answer(f"{name}: a snapshot taken" + (f" ({snap})" if snap else ""), self._run(ctx, c, *args, timeout=SNAPSHOT_S))

    def revert(self, name, snapshot, connection="system", accept_revert=False) -> dict:
        """A machine put back as it was in one of its snapshots: what changed since is lost, so asked twice."""
        name, c = domain_name(name), connection_of(connection)
        snap = str(snapshot if snapshot is not None else "").strip()
        if not snap:
            raise Refusal("which snapshot?")
        ctx = self._ready()
        self._domain(ctx, c, name)
        snaps = [s for s in self._run(ctx, c, "snapshot-list", "--domain", name, "--name", timeout=READ_S).splitlines() if s.strip()]
        if snap not in snaps:
            raise Refusal(f"{name} has no snapshot named {snap}: {', '.join(snaps) or 'it has none'}")
        if not yes(accept_revert):
            raise Refusal(f"reverting {name} to {snap} replaces its disks: what changed since that snapshot is lost for good",
                          accept="accept_revert")
        out = self._run(ctx, c, "snapshot-revert", "--domain", name, "--snapshotname", snap, timeout=SNAPSHOT_S)
        return answer(f"{name}: reverted to {snap}", out)

    def service(self, unit, action="start") -> dict:
        """One of libvirt's services started (as root: sudo -n when the platform is not); none is ever stopped."""
        if str(action or "start").strip().lower() != "start":
            raise Refusal("only start: a service is started here when asked, and never stopped")
        unit = str(unit or "").strip()
        if not UNIT.match(unit):
            raise Refusal(f"{unit!r} is not a service's name")
        ctx = self._ready()
        mine = {u.name: u for u in ctx.probe.units.values() if u.known and u.known.mode in (ctx.mode, "*")}
        u = mine.get(unit)
        if u is None:
            raise Refusal(f"{unit} is not one of libvirt's {ctx.mode} services here: {', '.join(sorted(mine)) or 'none is known'}")
        if u.up:
            return answer(f"{unit} is {u.state} already")
        if not u.startable:
            raise Refusal(f"{unit} is {u.state}: not started from here")
        cmd = start_command(ctx.probe.init, unit)
        try:
            out = ctx.shell.run(*cmd, timeout=SERVICE_S)
        except CommandError as e:
            if e.denied:
                raise LibvirtError(f"{e}; or start it yourself: sudo {' '.join(cmd)}", denied=True) from None
            raise
        return answer(f"{unit} started ({' '.join(cmd)})", out)

    def wake(self) -> dict:
        """libvirt's idle daemons and the session read now (connecting starts them), and from then on until the platform
        lets the plugin go."""
        ctx = self._ready()
        self._woken = True
        system = self._read(ctx, "system", self._system_parts(ctx))
        session = self._read(ctx, "session", ("domains",)) if self._session_read(ctx) else Connection("session", read=False)
        self._remember(ctx, (system, session))
        problems = [f"{c.uri}: {w}" for c in (system, session) for w in c.problems]
        lines = [f"{c.uri}: {plural(len(c.domains), 'virtual machine')}" for c in (system, session) if c.read and not c.problems]
        if problems:
            return {"said": f"read, with trouble: {problems[0]}", "lines": lines + problems[1:], "ok": False}
        return {"said": f"libvirt read: {plural(len(system.domains) + len(session.domains), 'virtual machine')}", "lines": lines, "ok": True}

    def run(self, *command: str, connection="system", **options) -> str:
        """virsh on a connection with these arguments, its output."""
        ctx = self._ready()
        if not command:
            raise Refusal("nothing to run")
        return self._run(ctx, connection_of(connection), *command, timeout=READ_S)


MACHINE = LibvirtPlugin()
