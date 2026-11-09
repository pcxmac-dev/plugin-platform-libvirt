"""libvirt over recorded outputs (nothing runs here): virsh on qemu:///system and qemu:///session through a stand-in
for this machine's commands; the modular daemons (Fedora) and the monolithic libvirtd (Debian, Gentoo's OpenRC), KVM,
the rights (the libvirt group, root, sudo -n, none), idle daemons and the session never woken by a read, a stopped
daemon started only when asked; forcing off and reverting asked twice; how each distribution installs it; only on a
native Linux machine: on Windows, macOS or in a WSL distribution nothing runs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from liminal_libs.machines import linux as linux_mod
from liminal_libs.machines.linux import Shell
from liminal_libs.machines.plugin import CommandError

from plugin_platform_libvirt import MACHINE, LibvirtError, LibvirtPlugin, Refusal, inventory, mode_of, system, why_not_native
from plugin_platform_libvirt.__main__ import main

RECORDED = Path(__file__).parent / "recorded"
OS = {
    "fedora": 'ID=fedora\nNAME="Fedora Linux"\nPRETTY_NAME="Fedora Linux 41 (Workstation Edition)"\nVERSION_ID=41',
    "debian": 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nNAME="Debian GNU/Linux"\nVERSION_ID="12"\nID=debian',
    "gentoo": 'NAME=Gentoo\nID=gentoo\nPRETTY_NAME="Gentoo Linux"\nVERSION_ID=2.17',
    "ubuntu": 'NAME="Ubuntu"\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nID=ubuntu\nID_LIKE=debian',
    "arch": 'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch',
    "alpine": 'NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.20.3\nPRETTY_NAME="Alpine Linux v3.20"',
    "rocky": 'NAME="Rocky Linux"\nVERSION_ID="9.4"\nID="rocky"\nID_LIKE="rhel centos fedora"\nPRETTY_NAME="Rocky Linux 9.4 (Blue Onyx)"',
    "opensuse": 'NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\nPRETTY_NAME="openSUSE Tumbleweed"',
}
ON = ("loaded", "active", "running", "enabled")
OFF = ("loaded", "inactive", "dead", "disabled")
LISTENING = ("loaded", "active", "listening", "enabled")
COMMON = {"virtlogd.service": ("loaded", "active", "running", "static"), "virtlogd.socket": ("loaded", "active", "running", "enabled"),
          "virtlockd.service": ("loaded", "inactive", "dead", "static"), "libvirt-guests.service": ("loaded", "active", "exited", "enabled")}
UNITS = {  # systemd's units as `systemctl show` says them: (LoadState, ActiveState, SubState, UnitFileState)
    "modular": {**COMMON, "virtqemud.service": ON, "virtqemud.socket": ("loaded", "active", "running", "enabled"),
                "virtnetworkd.service": ON, "virtnetworkd.socket": ("loaded", "active", "running", "enabled"),
                "virtstoraged.service": ON, "virtstoraged.socket": ("loaded", "active", "running", "enabled"),
                "libvirtd.service": OFF, "libvirtd.socket": OFF},
    "modular-idle": {**COMMON, "virtqemud.service": OFF, "virtqemud.socket": LISTENING, "virtnetworkd.service": OFF,
                     "virtnetworkd.socket": LISTENING, "virtstoraged.service": OFF, "virtstoraged.socket": LISTENING,
                     "libvirtd.service": OFF, "libvirtd.socket": OFF},
    "monolithic": {**COMMON, "libvirtd.service": ON, "libvirtd.socket": ("loaded", "active", "running", "enabled"),
                   "virtqemud.service": OFF, "virtqemud.socket": OFF},
    "monolithic-stopped": {**COMMON, "libvirtd.service": OFF, "libvirtd.socket": OFF},
}
MODULAR = dict(system_sockets=("libvirt-sock", "virtqemud-sock", "virtnetworkd-sock", "virtstoraged-sock"),
               system_daemons=("virtqemud", "virtnetworkd", "virtstoraged"))
DOMAINS = {"system": ("fedora40", "k3s-node", "win11"), "session": ("boxes-alpine",)}
ACTIVE_DOMAINS = {"system": ("fedora40", "k3s-node"), "session": ()}


def recorded(name: str) -> str:
    return (RECORDED / name).read_text(encoding="utf-8").rstrip("\n")


class FakeLinux:
    """Answers a Linux machine's commands for libvirt from recorded outputs: the probe (as the user), each connection's
    read (qemu:///system's as root when through sudo -n, qemu:///session's always the user's), the names virsh lists
    for a change, and the changes, which it records."""

    def __init__(self, os="fedora", init="systemd", units="modular", rc=(), user="ciara", uid=1000,
                 groups=("ciara", "wheel", "libvirt"), member=None, sudo=True, virsh="/usr/bin/virsh",
                 kvm=("dev", "rw", "kvm", "kvm_intel", "cpu:vmx"), system_sockets=MODULAR["system_sockets"],
                 system_daemons=MODULAR["system_daemons"], session_sockets=("virtqemud-sock",), session_daemons=("virtqemud",),
                 errors=None):
        self.os, self.init, self.user, self.uid, self.virsh = os, init, user, uid, virsh
        self.units = UNITS.get(units, {}) if isinstance(units, str) else dict(units)
        self.rc = list(rc)
        self.groups, self.member = tuple(groups), tuple(member if member is not None else groups)
        self.sudo, self.kvm = sudo, tuple(kvm)
        self.sockets = {"system": tuple(system_sockets), "session": tuple(session_sockets)}
        self.daemons = {"system": tuple(system_daemons), "session": tuple(session_daemons)}
        self.errors = dict(errors or {})  # a connection failing: system | session -> virsh's words
        self.calls: list[list[str]] = []
        self.reads: list[str] = []  # "sudo -n system domains,networks,pools"
        self.changes: list[list[str]] = []
        self.refuse: dict[str, str] = {}  # a change refused: its virsh command -> stderr

    def probe(self) -> str:
        lines = [system.MARK, f"== user {self.user} {self.uid}", f"== groups {' '.join(self.groups)}",
                 f"== member {' '.join(self.member)}", f"== init {self.init} {'systemd' if self.init == 'systemd' else 'init'}"]
        if self.virsh:
            lines += [f"== tool virsh {self.virsh}", "== version virsh 10.6.0"]
        lines += ["== os", OS[self.os], "== kvm" + "".join(f" {k}" for k in self.kvm)]
        for where in ("system", "session"):
            lines += [f"== socket {where} {s}" for s in self.sockets[where]]
            lines += [f"== daemon {where} {d}" for d in self.daemons[where]]
        if self.init == "systemd":
            lines.append("== units")
            for name in system.SYSTEMD_UNITS:
                load, active, sub, file_state = self.units.get(name, ("not-found", "inactive", "dead", ""))
                lines += [f"Id={name}", f"Description={name}", f"LoadState={load}", f"ActiveState={active}", f"SubState={sub}",
                          f"UnitFileState={file_state}", ""]
        else:
            lines += ["== openrc" if self.init == "openrc" else "== sysv", *self.rc]
        return "\n".join(lines + ["== end"]) + "\n"

    def read(self, where: str, script: str) -> str:
        out = [inventory.MARK]
        if "echo '== list'" in script:
            if where in self.errors:
                out += ["== list", "error: failed to connect to the hypervisor", f"error: {self.errors[where]}", "== rc 1"]
            else:
                out += ["== list", recorded(f"virsh-list-{where}.txt"), "== rc 0"]
                for name in DOMAINS[where]:
                    out += [f"== dominfo {name}", recorded(f"virsh-dominfo-{name}.txt"), f"== snapshots {name}",
                            recorded("virsh-snapshot-list-fedora40.txt" if name == "fedora40" else "virsh-snapshot-list-empty.txt")]
        if "echo '== nets'" in script:
            out += ["== nets", recorded("virsh-net-list.txt"), "== rc 0"]
        if "echo '== pools'" in script:
            out += ["== pools", recorded("virsh-pool-list-details.txt"), "== rc 0"]
        return "\n".join(out + ["== end"]) + "\n"

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        root = args[:2] == ["sudo", "-n"]
        cmd = args[2:] if root else args
        if root and not self.sudo:
            return 1, "", "sudo: a password is required\n"
        if cmd == ["true"]:
            return 0, "", ""
        if cmd[:2] == ["sh", "-c"]:
            script = cmd[2]
            if system.MARK in script:
                assert not root, "the probe never asks for root"
                return 0, self.probe(), ""
            assert inventory.MARK in script, f"an unknown script: {script[:80]!r}"
            where = "session" if "qemu:///session" in script else "system"
            assert not (root and where == "session"), "the session is never root's"
            parts = [p for p, word in (("domains", "== list"), ("networks", "== nets"), ("pools", "== pools")) if f"echo '{word}'" in script]
            self.reads.append(f"{'sudo -n ' if root else ''}{where} {','.join(parts)}")
            return 0, self.read(where, script), ""
        if cmd[0] in ("systemctl", "rc-service", "service"):
            self.changes.append(cmd)
            return 0, "", ""
        assert cmd[0] == self.virsh and cmd[1] == "-c", cmd
        where = "session" if cmd[2] == "qemu:///session" else "system"
        assert not (root and where == "session"), "the session is never root's"
        rest = cmd[3:]
        if rest == ["list", "--all", "--name"]:
            return 0, "".join(f"{n}\n" for n in DOMAINS[where]) + "\n", ""
        if rest == ["list", "--name"]:
            return 0, "".join(f"{n}\n" for n in ACTIVE_DOMAINS[where]) + "\n", ""
        if rest[:1] == ["snapshot-list"] and rest[-1] == "--name":
            return 0, ("clean-install\nbefore-update\n\n" if rest[2] == "fedora40" else "\n"), ""
        self.changes.append(cmd)
        if rest[0] in self.refuse:
            return 1, "", self.refuse[rest[0]]
        return 0, f"Domain '{rest[2] if len(rest) > 2 else ''}' done\n\n", ""


@pytest.fixture(autouse=True)
def user(monkeypatch):
    """The platform runs as a user (uid 1000) here; a test that wants root says so."""
    monkeypatch.setattr(linux_mod.os, "geteuid", lambda: 1000, raising=False)


def plugin(fake) -> LibvirtPlugin:
    """The plugin on a native Linux machine (the test's word), its commands through the stand-in."""
    return LibvirtPlugin(shell=Shell("local", runner=fake), native="")


def table(st: dict, title: str) -> dict:
    return next(t for t in st["tables"] if t["title"] == title)


def texts(row: list) -> list:
    return [c["text"] if isinstance(c, dict) and "text" in c else c.get("title") if isinstance(c, dict) else c for c in row]


def ask_page(p, st: dict, button: dict, accepted=()):
    """A hook asked as the platform's page asks it (platform.js: openForm, argsOf): the button's form, its values over
    the fields' own, each field in order (an empty one as null, an accept field true only once accepted)."""
    form = next(f for f in st["forms"] if f["id"] == button["form"])
    args = []
    for f in form["fields"]:
        if f["type"] == "accept":
            args.append(f["name"] in accepted)
            continue
        v = button.get("values", {}).get(f["name"], f.get("value"))
        if v is None and f["type"] == "choice":
            v = f["choices"][0]["value"]
        args.append(None if v in (None, "") else v)
    return p.ask(form["hook"], *args)


SYS = ["/usr/bin/virsh", "-c", "qemu:///system"]


def test_the_plugin_its_hooks_and_its_probe():
    assert (MACHINE.name, MACHINE.title, MACHINE.ICON, MACHINE.KIND, MACHINE.STEPS, MACHINE.options) == (
        "libvirt", "libvirt", "libvirt", "machine", (), ())
    assert set(LibvirtPlugin(native="").interface()["hooks"]) == {"present", "status", "run", "power", "autostart", "snapshot",
                                                                  "revert", "service", "wake"}
    for word in ("virsh", "/dev/kvm", "kvm_intel", "kvm_amd", "vmx|svm", "pgrep -u 0", "XDG_RUNTIME_DIR", "virtqemud.socket",
                 "libvirtd.service", "libvirt-guests", "/run/openrc/", "/etc/runlevels/", "LC_ALL=C"):
        assert word in system.PROBE
    assert "sudo" not in system.PROBE and not re.search(r"\bstart\b", system.PROBE)  # asks nothing of root, starts nothing


def test_fedoras_modular_daemons_both_connections_as_a_member_of_libvirt():
    fake = FakeLinux()
    st = plugin(fake).status()
    assert (st["present"], st["valid"], st["why"]) == (True, True, "") and "problem" not in st
    assert st["summary"] == "libvirt 10.6.0 (virsh): 4 virtual machines, 2 running"
    assert (st["daemons"], st["system"], st["session"]) == (
        "modular: virtqemud, virtnetworkd, virtstoraged (systemd's sockets start them)",
        "qemu:///system running (virtqemud, virtnetworkd, virtstoraged)", "qemu:///session running (ciara's virtqemud)")
    assert st["kvm"] == "/dev/kvm present (kvm_intel loaded); ciara may open it"
    assert st["rights"] == "ciara is in libvirt: qemu:///system as ciara, no sudo; qemu:///session as the user always"
    assert (st["machines"], st["snapshots"]) == ("4: 2 running · 3 on qemu:///system, 1 on qemu:///session", "2")
    assert st["networks"] == "default (active), isolated (inactive)"
    assert st["storagePools"] == "default (running, 266.76 GiB free), iso (inactive)"
    rows = table(st, "Virtual machines")["rows"]
    assert [texts(r)[:5] for r in rows] == [["fedora40", "running", "4", "8.0 GiB", "on"], ["k3s-node", "paused", "2", "2.0 GiB", "off"],
                                            ["win11", "shut off", "4", "8.0 GiB", "off"], ["boxes-alpine", "shut off", "1", "1.0 GiB", "off"]]
    assert rows[1][3] == {"text": "2.0 GiB", "sub": "of 4.0 GiB at most"} and rows[3][0] == {"text": "boxes-alpine", "sub": "qemu:///session"}
    assert rows[0][4] == {"form": "autostart", "title": "on", "values": {"name": "fedora40", "connection": "system", "on": "off"},
                          "label": "Turn autostart off for fedora40"}
    assert rows[0][5] == {"form": "power", "title": "Shut down…", "values": {"name": "fedora40", "connection": "system", "action": "shutdown"},
                          "label": "Start, shut down, reboot or force off fedora40"}
    assert rows[2][5]["title"] == "Start…" and rows[3][6]["values"] == {"name": "boxes-alpine", "connection": "session"}
    snaps = table(st, "Snapshots")["rows"]
    assert [texts(r)[:4] for r in snaps] == [["fedora40", "clean-install", "2024-04-30 21:12 +0200", "shutoff"],
                                             ["fedora40", "before-update", "2024-05-11 08:01 +0200", "running"]]
    assert snaps[1][4]["values"] == {"name": "fedora40", "snapshot": "before-update", "connection": "system"}
    assert [texts(r) for r in table(st, "Networks")["rows"]] == [["default", "active", "yes", "yes"], ["isolated", "inactive", "no", "yes"]]
    assert [texts(r) for r in table(st, "Storage pools")["rows"]] == [["default", "running", "yes", "467.89 GiB", "201.13 GiB", "266.76 GiB"],
                                                                      ["iso", "inactive", "no", "-", "-", "-"]]
    daemons = [texts(r)[:3] for r in table(st, "Daemons")["rows"]]
    assert daemons[:3] == [["virtnetworkd.service", "running", "enabled"], ["virtqemud.service", "running", "enabled"],
                           ["virtstoraged.service", "running", "enabled"]]
    assert not any(d[0].startswith("libvirtd") for d in daemons) and ["virtlockd.service", "stopped", "static"] in daemons
    assert {f["id"] for f in st["forms"]} == {"power", "autostart", "snapshot", "revert", "service", "wake"} and st["actions"] == []
    accept = {f["id"]: [x["name"] for x in f["fields"] if x["type"] == "accept"] for f in st["forms"]}
    assert accept == {"power": ["accept_destroy"], "autostart": [], "snapshot": [], "revert": ["accept_revert"], "service": [], "wake": []}
    assert fake.reads == ["system domains,networks,pools", "session domains"]
    assert not any(c[0] == "sudo" for c in fake.calls) and fake.changes == []  # as the user; nothing changed by a read


def test_machines_changed_only_through_their_hooks_forcing_off_and_reverting_asked_twice():
    fake = FakeLinux()
    p = plugin(fake)
    assert p.power("win11", "start")["said"] == "win11: started"
    p.power("fedora40", "shutdown")
    p.power("k3s-node", "reboot")
    p.power("boxes-alpine", "start", "session")
    assert fake.changes == [[*SYS, "start", "--domain", "win11"], [*SYS, "shutdown", "--domain", "fedora40"],
                            [*SYS, "reboot", "--domain", "k3s-node"], ["/usr/bin/virsh", "-c", "qemu:///session", "start", "--domain", "boxes-alpine"]]
    fake.changes.clear()
    with pytest.raises(Refusal) as asked:
        p.power("fedora40", "destroy")
    assert asked.value.accept == "accept_destroy" and "cuts its power at once" in str(asked.value) and fake.changes == []
    with pytest.raises(Refusal, match="win11 is not running: nothing to force off"):
        p.power("win11", "destroy", accept_destroy=True)
    assert p.power("fedora40", "destroy", accept_destroy="true")["said"] == "fedora40: forced off"
    p.autostart("win11", "on")
    p.autostart("fedora40", False)
    p.snapshot("win11", "pre-patch", "before Patch Tuesday")
    p.snapshot("k3s-node")
    assert fake.changes == [[*SYS, "destroy", "--domain", "fedora40"], [*SYS, "autostart", "--domain", "win11"],
                            [*SYS, "autostart", "--domain", "fedora40", "--disable"],
                            [*SYS, "snapshot-create-as", "--domain", "win11", "--name", "pre-patch", "--description", "before Patch Tuesday", "--atomic"],
                            [*SYS, "snapshot-create-as", "--domain", "k3s-node", "--atomic"]]
    fake.changes.clear()
    with pytest.raises(Refusal) as asked:
        p.revert("fedora40", "clean-install")
    assert asked.value.accept == "accept_revert" and fake.changes == []
    assert p.revert("fedora40", "clean-install", accept_revert=True)["said"] == "fedora40: reverted to clean-install"
    assert fake.changes == [[*SYS, "snapshot-revert", "--domain", "fedora40", "--snapshotname", "clean-install"]]
    with pytest.raises(Refusal, match="fedora40 has no snapshot named nope: clean-install, before-update"):
        p.revert("fedora40", "nope", accept_revert=True)
    with pytest.raises(Refusal, match="no virtual machine named ghost on qemu:///system"):
        p.power("ghost", "start")
    for bad in (lambda: p.power("win11", "explode"), lambda: p.snapshot("win11", "a b"), lambda: p.autostart("win11", "maybe"),
                lambda: p.power("win11", "start", "qemu:///other"), lambda: p.power("bad\nname", "start"),
                lambda: p.snapshot("win11", None, "two\nlines")):
        with pytest.raises(Refusal):
            bad()
    fake.refuse["snapshot-create-as"] = "error: Operation not supported: internal snapshots of a VM with pflash based firmware are not supported\n"
    with pytest.raises(LibvirtError, match="^Operation not supported: internal snapshots"):
        p.snapshot("win11", "uefi")


def test_the_page_asks_each_hook_with_its_forms_fields_in_order():
    fake = FakeLinux()
    p = plugin(fake)
    st = p.status()
    rows = {texts(r)[0]: r for r in table(st, "Virtual machines")["rows"]}
    ask_page(p, st, rows["fedora40"][5])  # Shut down…
    with pytest.raises(Refusal) as asked:
        ask_page(p, st, {**rows["fedora40"][5], "values": {**rows["fedora40"][5]["values"], "action": "destroy"}})
    ask_page(p, st, {**rows["fedora40"][5], "values": {**rows["fedora40"][5]["values"], "action": "destroy"}}, accepted=(asked.value.accept,))
    ask_page(p, st, rows["fedora40"][4])  # autostart off
    ask_page(p, st, rows["boxes-alpine"][6])  # a snapshot in the session
    revert = table(st, "Snapshots")["rows"][0][4]
    with pytest.raises(Refusal) as asked:
        ask_page(p, st, revert)
    ask_page(p, st, revert, accepted=(asked.value.accept,))
    assert fake.changes == [[*SYS, "shutdown", "--domain", "fedora40"], [*SYS, "destroy", "--domain", "fedora40"],
                            [*SYS, "autostart", "--domain", "fedora40", "--disable"],
                            ["/usr/bin/virsh", "-c", "qemu:///session", "snapshot-create-as", "--domain", "boxes-alpine", "--atomic"],
                            [*SYS, "snapshot-revert", "--domain", "fedora40", "--snapshotname", "clean-install"]]
    assert ask_page(p, st, {"form": "wake"})["said"] == "libvirt read: 4 virtual machines"


def test_debians_libvirtd_under_systemd_and_gentoos_under_openrc(monkeypatch):
    debian = FakeLinux(os="debian", units="monolithic", system_sockets=("libvirt-sock",), system_daemons=("libvirtd",),
                       session_sockets=(), session_daemons=())
    st = plugin(debian).status()
    assert st["daemons"] == "monolithic: libvirtd" and st["system"] == "qemu:///system running (libvirtd)"
    assert [r[0] for r in table(st, "Daemons")["rows"]][:2] == ["libvirtd.service", "libvirtd.socket"]
    assert not any(r[0].startswith("virtqemud") for r in table(st, "Daemons")["rows"])
    stopped = FakeLinux(os="debian", units="monolithic-stopped", system_sockets=(), system_daemons=(), session_sockets=(), session_daemons=())
    st = plugin(stopped).status()
    assert st["problem"].startswith("libvirt's libvirtd is stopped: Start… under Daemons starts it") and stopped.reads == []
    assert st["summary"] == "libvirt 10.6.0 (virsh): libvirt's daemon is stopped"
    start = {r[0]: r[4] for r in table(st, "Daemons")["rows"]}["libvirtd.service"]
    assert start == {"form": "service", "title": "Start…", "values": {"unit": "libvirtd.service", "action": "start"}, "label": "Start libvirtd.service"}
    assert plugin(stopped).service("libvirtd.service")["said"] == "libvirtd.service started (systemctl start libvirtd.service)"
    assert stopped.calls[-1] == ["sudo", "-n", "systemctl", "start", "libvirtd.service"]
    with pytest.raises(Refusal, match="not one of libvirt's monolithic services here"):
        plugin(stopped).service("virtqemud.socket")
    with pytest.raises(Refusal, match="never stopped"):
        plugin(stopped).service("libvirtd.service", "stop")
    gentoo = FakeLinux(os="gentoo", init="openrc", units={}, rc=["libvirtd started default", "virtlogd started -",
                       "virtlockd stopped -", "libvirt-guests stopped -"], system_sockets=("libvirt-sock",),
                       system_daemons=("libvirtd",), session_sockets=(), session_daemons=())
    st = plugin(gentoo).status()
    assert (st["daemons"], st["initSystem"], st["distribution"]) == ("monolithic: libvirtd", "OpenRC (PID 1: init)", "Gentoo Linux")
    assert [texts(r)[:3] for r in table(st, "Daemons")["rows"]] == [["libvirtd", "running", "default"], ["libvirt-guests", "stopped", "–"],
                                                                    ["virtlockd", "stopped", "–"], ["virtlogd", "running", "–"]]
    monkeypatch.setattr(linux_mod.os, "geteuid", lambda: 0, raising=False)
    plugin(gentoo).service("libvirt-guests", "start")
    assert gentoo.calls[-1] == ["rc-service", "libvirt-guests", "start"]
    gone = FakeLinux(os="gentoo", init="openrc", units={}, rc=["libvirtd stopped -", "virtlogd stopped -"], system_sockets=(),
                     system_daemons=(), session_sockets=(), session_daemons=())
    st = plugin(gone).status()
    assert st["system"] == "qemu:///system stopped (libvirtd): Start… under Daemons starts it"
    devuan = FakeLinux(os="debian", init="sysvinit", units={}, rc=["libvirtd 3", "libvirt-guests 3"], system_sockets=(),
                       system_daemons=(), session_sockets=(), session_daemons=())
    plugin(devuan).service("libvirtd", "start")
    assert devuan.calls[-1] == ["service", "libvirtd", "start"]
    suse = FakeLinux(os="opensuse", units={"virtqemud.service": OFF, "libvirtd.service": OFF})
    assert mode_of(system.parse(suse.probe())) == "modular"  # neither set to start: openSUSE's default


def test_idle_daemons_and_the_session_are_read_only_when_asked():
    fake = FakeLinux(units="modular-idle", system_daemons=(), session_sockets=(), session_daemons=())
    p = plugin(fake)
    st = p.status()
    assert fake.reads == [] and st["valid"] and "problem" not in st  # no socket was touched
    assert st["summary"] == "libvirt 10.6.0 (virsh): libvirt's daemon is idle (Read now… reads it)"
    assert st["system"] == ("qemu:///system idle: virtqemud.socket, virtnetworkd.socket, virtstoraged.socket listen and start their "
                            "daemons for the first client; read when asked (Read now)")
    assert st["session"] == "qemu:///session: no session daemon running for ciara, and virsh would start one; read when asked (Read now)"
    assert st["actions"] == [{"form": "wake", "title": "Read now…", "note": "connects to libvirt's idle daemons, which starts them"}]
    assert table(st, "Virtual machines")["empty"] == ("Not read: qemu:///system is idle (virtqemud.socket listens): Read now… reads it; "
                                                      "qemu:///session has no daemon running: Read now… reads it, which starts the user's own.")
    assert [t["title"] for t in st["tables"]] == ["Virtual machines", "Snapshots", "Daemons"]
    assert p.wake()["said"] == "libvirt read: 4 virtual machines"
    assert fake.reads == ["system domains,networks,pools", "session domains"]
    st = p.status()
    assert st["actions"] == [] and "Networks" in [t["title"] for t in st["tables"]] and len(fake.reads) == 4
    p.detach()
    p.status()
    assert len(fake.reads) == 4  # let go: idle again until asked


def test_the_rights_the_libvirt_group_root_sudo_and_none(monkeypatch):
    sudo = FakeLinux(groups=("ciara", "wheel"))
    st = plugin(sudo).status()
    assert st["rights"] == "ciara is not in libvirt: qemu:///system as root through sudo -n; qemu:///session as the user always"
    assert sudo.reads == ["sudo -n system domains,networks,pools", "session domains"]
    kept = FakeLinux(groups=("ciara", "wheel"), sudo=False)
    again = plugin(kept)
    again.status()
    again.status()
    assert kept.calls.count(["sudo", "-n", "true"]) == 1  # sudo's answer kept: a refusal is not logged by sudo every read
    plugin(sudo).power("win11", "start")
    assert sudo.calls[-1] == ["sudo", "-n", *SYS, "start", "--domain", "win11"]
    plugin(sudo).power("boxes-alpine", "start", "session")
    assert sudo.calls[-1] == ["/usr/bin/virsh", "-c", "qemu:///session", "start", "--domain", "boxes-alpine"]
    none = FakeLinux(groups=("ciara", "wheel"), sudo=False)
    st = plugin(none).status()
    assert st["valid"] and none.reads == ["session domains"]  # the session is still the user's own
    assert st["problem"].startswith("qemu:///system is not read: ciara is neither root nor in libvirt, and sudo asks for a password: "
                                    "add ciara to libvirt (sudo usermod -aG libvirt ciara) and log in again")
    assert [texts(r)[0] for r in table(st, "Virtual machines")["rows"]] == ["boxes-alpine"]
    with pytest.raises(LibvirtError, match="sudo usermod -aG libvirt ciara") as e:
        plugin(none).power("win11", "start")
    assert e.value.denied and none.changes == []
    later = FakeLinux(groups=("ciara", "wheel"), member=("ciara", "wheel", "libvirt"), sudo=False)
    assert "was added to libvirt after this login" in plugin(later).status()["rights"]
    polkit = FakeLinux(errors={"system": "authentication unavailable: no polkit agent available to authenticate action 'org.libvirt.unix.manage'"})
    st = plugin(polkit).status()
    assert "qemu:///system: failed to connect to the hypervisor; authentication unavailable" in st["problem"]
    assert "sudo usermod -aG libvirt ciara" in st["problem"]
    monkeypatch.setattr(linux_mod.os, "geteuid", lambda: 0, raising=False)
    root = FakeLinux(uid=0, user="root", groups=("root",), session_sockets=(), session_daemons=())
    st = plugin(root).status()
    assert st["rights"] == "the platform runs as root" and st["session"].startswith("qemu:///session not read: the platform runs as root")
    assert root.reads == ["system domains,networks,pools"] and not any(c[0] == "sudo" for c in root.calls)
    with pytest.raises(Refusal, match="would be root's own"):
        plugin(root).power("boxes-alpine", "start", "session")


def test_kvm_said_as_it_is():
    def words(kvm, user="ciara"):
        return system.kvm_words(system.Probe(user=user, kvm=frozenset(kvm)))
    assert words(("dev", "rw", "kvm", "kvm_amd", "cpu:svm")) == ("/dev/kvm present (kvm_amd loaded); ciara may open it", True)
    assert words(("dev", "kvm"))[0] == ("/dev/kvm present (built into the kernel); ciara may not open it, which qemu:///session's "
                                         "machines need: the kvm group (sudo usermod -aG kvm ciara)")
    assert words(("cpu:vmx",)) == ("no /dev/kvm, though the processor has vmx: load kvm_intel (sudo modprobe kvm_intel), or turn "
                                   "virtualization on in the firmware (BIOS/UEFI); without it the machines are emulated, slowly", False)
    assert words(())[0].startswith("no /dev/kvm, and the processor shows neither vmx nor svm")
    st = plugin(FakeLinux(kvm=())).status()
    assert st["valid"] and "no /dev/kvm" in st["problem"]


def test_not_installed_says_how_each_distribution_installs_it():
    def why(os):
        st = plugin(FakeLinux(os=os, virsh="", units={}, system_sockets=(), system_daemons=(), session_sockets=(), session_daemons=())).status()
        assert (st["present"], st["valid"], st["summary"]) == (False, False, "not installed")
        return st["why"]
    assert "emerge --ask app-emulation/libvirt" in why("gentoo") and "rc-update add libvirtd default" in why("gentoo")
    assert "libvirt-daemon-system" in why("ubuntu") and "qemu-system" in why("debian") and "@virtualization" in why("fedora")
    assert "virtqemud.socket" in why("rocky") and "pacman -S libvirt" in why("arch") and "rc-update add libvirtd" in why("alpine")
    assert "kvm_server" in why("opensuse")
    assert why("arch").endswith("then add ciara to libvirt (sudo usermod -aG libvirt ciara) and log in again")


def test_parsing_virsh():
    c = inventory.parse(f"{inventory.MARK}\n== list\n{recorded('virsh-list-system.txt')}\n== rc 0\n== end\n")
    assert [(d.id, d.name, d.state) for d in c.domains] == [("3", "fedora40", "running"), ("7", "k3s-node", "paused"), ("-", "win11", "shut off")]
    assert inventory.dominfo(recorded("virsh-dominfo-fedora40.txt").splitlines())["Security label"] == "system_u:system_r:svirt_t:s0:c117,c839 (enforcing)"
    down = inventory.parse(f"{inventory.MARK}\n== list\nerror: failed to connect to the hypervisor\nerror: Failed to connect socket to "
                           f"'/var/run/libvirt/virtqemud-sock': No such file or directory\n== rc 1\n== end\n")
    assert down.down and not down.denied and down.problems == [
        "failed to connect to the hypervisor; Failed to connect socket to '/var/run/libvirt/virtqemud-sock': No such file or directory"]
    denied = inventory.parse(f"{inventory.MARK}\n== list\nerror: failed to connect to the hypervisor\nerror: Failed to connect socket to "
                             f"'/var/run/libvirt/libvirt-sock': Permission denied\n== rc 1\n== end\n")
    assert denied.denied
    assert inventory.parse("something else").problems == ["the read's answer was not understood"]
    assert system.parse("something else").problem == "the probe's answer was not understood"
    empty = inventory.parse(f"{inventory.MARK}\n== snapshots x\n{recorded('virsh-snapshot-list-empty.txt')}\n== end\n")
    assert empty.domains == [] and empty.problems == []


def test_the_command_line(capsys):
    fake = FakeLinux()
    p = plugin(fake)
    assert main(["status"], machine=p) == 0 and json.loads(capsys.readouterr().out)["summary"].endswith("4 virtual machines, 2 running")
    assert main(["destroy", "fedora40"], machine=p) == 1
    err = capsys.readouterr().err
    assert err.startswith("refused: forcing fedora40 off cuts its power") and err.rstrip().endswith("(again with --yes to go on)")
    assert main(["destroy", "fedora40", "--yes"], machine=p) == 0 and capsys.readouterr().out.startswith("fedora40: forced off")
    assert main(["revert", "fedora40", "clean-install", "--yes"], machine=p) == 0
    assert main(["autostart", "win11", "on"], machine=p) == 0
    assert main(["snapshot", "boxes-alpine", "first", "--description", "fresh", "--session"], machine=p) == 0
    assert main(["start", "boxes-alpine", "--session"], machine=p) == 0
    assert main(["run", "--", "domstate", "win11"], machine=p) == 0
    assert fake.changes == [[*SYS, "destroy", "--domain", "fedora40"],
                            [*SYS, "snapshot-revert", "--domain", "fedora40", "--snapshotname", "clean-install"],
                            [*SYS, "autostart", "--domain", "win11"],
                            ["/usr/bin/virsh", "-c", "qemu:///session", "snapshot-create-as", "--domain", "boxes-alpine", "--name", "first",
                             "--description", "fresh", "--atomic"],
                            ["/usr/bin/virsh", "-c", "qemu:///session", "start", "--domain", "boxes-alpine"],
                            [*SYS, "domstate", "win11"]]
    capsys.readouterr()
    assert main(["frobnicate"], machine=p) == 2 and main(["autostart", "win11", "maybe"], machine=p) == 2 and main(["run"], machine=p) == 2


def test_only_a_native_linux_machine_is_driven():
    """The user, 2026-11-08: "the scope of linux administration is only on native linux O/S"; "it's not for administrating
    WSL instances": on Windows, macOS or in a WSL distribution no command runs at all, the status says why with applies
    False (the platform shows "Not for this machine", no setup), and every hook is refused."""
    windows = why_not_native("win32", "10", {})
    assert windows == "libvirt is for a native Linux machine, and this one runs Windows; Liminal's WSL distributions are the WSL plugins'"
    wsl = why_not_native("linux", "5.15.167.4-microsoft-standard-WSL2", {"WSL_DISTRO_NAME": "Liminal-Fedora"})
    assert wsl.endswith("not a WSL instance, and this is WSL's Liminal-Fedora on Windows")
    mac = why_not_native("darwin", "24.1.0", {})
    assert "this one runs macOS" in mac and why_not_native("linux", "6.11.5-300.fc41.x86_64", {}) == ""
    if sys.platform == "win32":
        assert MACHINE.not_for_here() == windows and not MACHINE.present()  # this PC: asked nothing
    for note in (windows, wsl, mac):
        ran: list = []
        p = LibvirtPlugin(shell=Shell("local", runner=lambda args, timeout: ran.append(args) or (0, "", "")), native=note)
        st = p.status()
        assert (st["present"], st["valid"], st["applies"], st["summary"], st["why"]) == (False, False, False, "not for this machine", note)
        assert (st["tables"], st["forms"], st["actions"]) == ([], [], []) and not p.present() and p.setup(log=lambda m: None) == []
        for ask in (lambda: p.power("win11", "start"), lambda: p.power("win11", "destroy", accept_destroy=True),
                    lambda: p.autostart("win11", "on"), lambda: p.snapshot("win11"), lambda: p.revert("win11", "x", accept_revert=True),
                    lambda: p.service("libvirtd.service"), p.wake, lambda: p.run("list")):
            with pytest.raises(CommandError, match="native Linux machine"):
                ask()
        assert ran == []  # nothing ran anywhere
    in_wsl = LibvirtPlugin(shell=Shell("wsl:Liminal-Fedora", runner=lambda args, timeout: (0, "", "")), native="")
    with pytest.raises(LibvirtError, match="never WSL's Liminal-Fedora"):
        in_wsl.power("win11", "start")
