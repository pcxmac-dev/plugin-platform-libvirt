"""What the plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its attached
to, and present links that provide documentation"): its cards are sound; they name every command the plugin runs (the
probe's and the read's as their scripts write them, each change's as the stand-in machine was given it, under systemd,
OpenRC and SysV scripts) and none it does not; its facts ask nothing; and, with LIMINAL_VENDOR_PAGES=1 alone, every
address on them answers (the only test here that reaches the network)."""
from __future__ import annotations

import os
import re

import pytest

import plugin_platform_libvirt as lv
from liminal_libs.machines import linux as linux_mod
from liminal_libs.sources import apis as A
from liminal_libs.sources.conformance import problems
from plugin_platform_libvirt import apis as cards
from plugin_platform_libvirt import inventory, system
from test_plugin import FakeLinux, plugin


def virsh_verb(words) -> str:
    """A virsh command by its command word, its connection and arguments left out: list, snapshot-revert, --version."""
    words = list(words)
    if words[:2] == ["sudo", "-n"]:
        words = words[2:]
    words = words[1:]  # virsh itself
    if words[:1] == ["-c"]:
        words = words[2:]
    return words[0]


def service_shape(words) -> str:
    words = list(words)
    if words[:2] == ["sudo", "-n"] and words[2:] != ["true"]:
        words = words[2:]
    tool, rest = words[0], words[1:]
    if tool in ("rc-service", "service"):
        return f"{tool} {rest[-1]}"
    if tool in ("systemctl", "rc-update"):
        return f"{tool} {rest[0]}"
    return " ".join(words) if tool == "sudo" else tool


def card(name: str) -> A.Api:
    return next(a for a in lv.MACHINE.apis if a.name == name)


def test_its_cards_are_sound_and_written_for_plugin_api_2_2():
    p = lv.MACHINE
    assert p.api == "2.2" and problems(p) == [] and A.problems(p.apis) == []
    assert [a.name for a in p.apis] == [cards.VIRSH, cards.DAEMONS, cards.KVM]
    for a in p.apis:
        assert a.verified == "2026-11-11" and a.docs.startswith("https://") and a.used and a.covered
        assert all(c.area in {x.name for x in a.areas} for c in a.calls), a.name
        assert len(a.areas) > len(a.covered) and len(a.calls) > len(a.used)  # more of the API than the plugin uses


def test_the_virsh_card_names_every_command_the_plugin_runs_and_no_other():
    fake = FakeLinux()
    p = plugin(fake)
    p.status()
    p.power("win11", "start")
    p.power("fedora40", "shutdown")
    p.power("k3s-node", "reboot")
    p.power("fedora40", "destroy", accept_destroy=True)
    p.autostart("win11", "on")
    p.autostart("fedora40", False)
    p.snapshot("win11", "pre-patch", "before Patch Tuesday")
    p.revert("fedora40", "clean-install", accept_revert=True)
    ran = {virsh_verb(c) for c in fake.calls if "/usr/bin/virsh" in c[:3]}
    script = inventory.read_script("/usr/bin/virsh", "system")
    ran |= set(re.findall(r"/usr/bin/virsh -c qemu:///system ([a-z-]+)", script))  # the read's, as its script writes them
    assert '"$v" --version' in system.PROBE  # the probe's
    ran.add("--version")
    claimed = {c.name.split()[1] for c in card(cards.VIRSH).used}
    assert ran == claimed, ran ^ claimed
    writes = {c.name.split()[1] for c in card(cards.VIRSH).used if c.writes}
    assert writes == {"start", "shutdown", "reboot", "destroy", "autostart", "snapshot-create-as", "snapshot-revert"}
    for c in card(cards.VIRSH).used:  # each beside the libvirt function it is (the API reference's), but virsh's own
        assert c.name == "virsh --version" or re.search(r"\(vir[A-Z]\w+\)", c.about), c.name


def test_the_daemons_card_names_what_is_asked_of_the_machine(monkeypatch):
    stopped = FakeLinux(os="debian", units="monolithic-stopped", system_sockets=(), system_daemons=(), session_sockets=(),
                        session_daemons=())
    plugin(stopped).service("libvirtd.service")
    outsider = FakeLinux(groups=("ciara", "wheel"))  # not in libvirt: root's commands through sudo -n, asked first
    plugin(outsider).status()
    monkeypatch.setattr(linux_mod.os, "geteuid", lambda: 0, raising=False)  # as root: rc-service and service as they are
    gentoo = FakeLinux(os="gentoo", init="openrc", units={}, rc=["libvirt-guests stopped -"], system_sockets=(),
                       system_daemons=(), session_sockets=(), session_daemons=())
    plugin(gentoo).service("libvirt-guests", "start")
    devuan = FakeLinux(os="debian", init="sysvinit", units={}, rc=["libvirtd 3"], system_sockets=(), system_daemons=(),
                       session_sockets=(), session_daemons=())
    plugin(devuan).service("libvirtd", "start")
    ran = {service_shape(c) for f in (stopped, outsider, gentoo, devuan) for c in f.calls
           if "sh" not in c[:3] and "/usr/bin/virsh" not in c[:3]}
    for shape, written in (("systemctl show", "systemctl show -p Id,LoadState,ActiveState,SubState,UnitFileState,Description"),
                           ("service status", 'service "$n" status'), ("pgrep", 'pgrep -u 0 -x "$d"'), ("id", "id -nG")):
        assert written in system.PROBE, written  # the probe's, as its script writes them
        ran.add(shape)
    claimed = {service_shape(c.name.split()) for c in card(cards.DAEMONS).used}
    assert ran == claimed, ran ^ claimed
    assert {service_shape(c.name.split()) for c in card(cards.DAEMONS).used if c.writes} == {
        "systemctl start", "rc-service start", "service start"}  # started when asked, never stopped


def test_the_kvm_card_names_what_the_probe_looks_at():
    for written in ("[ -c /dev/kvm ]", "[ -r /dev/kvm ] && [ -w /dev/kvm ]", '[ -d "/sys/module/$m" ]',
                    "for m in kvm kvm_intel kvm_amd", "-owE 'vmx|svm' /proc/cpuinfo"):
        assert written in system.PROBE, written
    assert len(card(cards.KVM).used) == 3 and not any(c.writes for c in card(cards.KVM).used)
    assert not any(c.costs for a in lv.MACHINE.apis for c in a.calls)


def test_its_facts_say_what_it_learned_and_ask_nothing():
    assert lv.LibvirtPlugin(native="").api_facts() == {}  # nothing looked at yet: nothing asked
    fake = FakeLinux()
    p = plugin(fake)
    p.status()
    before = len(fake.calls)
    facts = A.facts_of(p)
    assert len(fake.calls) == before  # asked nothing to answer
    assert facts[cards.VIRSH]["virsh"] == "/usr/bin/virsh (10.6.0)"
    assert re.match(r"\d+ machines \(\d+ running\), \d+ snapshots, \d+ networks, \d+ pools$", facts[cards.VIRSH]["qemu:///system"])
    assert facts[cards.DAEMONS]["Daemons"].startswith("modular: virtqemud") and facts[cards.DAEMONS]["Init system"].startswith("systemd")
    assert facts[cards.KVM]["KVM"].startswith("/dev/kvm present")
    p.detach()
    assert p.api_facts() == {}  # let go: what it learned goes


@pytest.mark.skipif(os.environ.get("LIMINAL_VENDOR_PAGES") != "1", reason="reaches the makers' pages: LIMINAL_VENDOR_PAGES=1")
def test_every_address_on_its_cards_answers(monkeypatch):
    monkeypatch.undo()  # this test alone reaches the network (conftest refuses it to every other)
    assert A.dead_links(lv.MACHINE.apis) == []
