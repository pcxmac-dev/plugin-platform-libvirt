"""Who may ask the plugin's changes (0.3.1, the sweep after the review's PLT-H1, 2026-11-25). Its changes are asked only
from its page (PAGE_ONLY_HOOKS, as liminal-libs 1.66.0's apps/asking.py and liminal-platform 0.34.0 read them): a
machine started, shut down, rebooted or forced off, its autostart, a snapshot taken or reverted to, one of libvirt's
services started, and the read that starts its idle daemons (Read now). Another plugin's ask is refused, and so is an
ask that names no one; over HTTP the platform also asks its login whether you are at the page. Before, any program on
this machine asked them with two headers, a second confirmation being only an argument: a machine forced off, or
reverted to a snapshot, with the platform's rights over qemu:///system. Its status is asked by anyone, as before. Asked
through the library's own App (its ask names who asks as the platform's does), over the stand-in for this machine's
commands: nothing runs."""
from __future__ import annotations

import pytest

pytest.importorskip("liminal_libs.apps.asking", reason="no hook is asked only from its page before liminal-libs 1.66.0")

from liminal_libs import internal  # noqa: E402 - after the skip, as each of these
from liminal_libs.apps import App, asking  # noqa: E402
from liminal_libs.apps.authorization import EnvironmentLogin  # noqa: E402
from liminal_libs.machines import linux as linux_mod  # noqa: E402
from liminal_libs.machines.plugin import MachinePlugin  # noqa: E402
from plugin_platform_libvirt import MACHINE  # noqa: E402
from test_plugin import SUDO, SYS, FakeLinux, plugin  # noqa: E402

CHANGES = ("power", "autostart", "snapshot", "revert", "service", "wake")
READS = ("present", "status")
ASKS = {  # each change as an ask, every confirmation said, and the command it runs when its page asks it
    "power": (("fedora40", "destroy", "system", True), [*SYS, "destroy", "--domain", "fedora40"]),  # forced off
    "autostart": (("win11", "on"), [*SYS, "autostart", "--domain", "win11"]),
    "snapshot": (("win11", "pre-patch"), [*SYS, "snapshot-create-as", "--domain", "win11", "--name", "pre-patch",
                                          "--atomic"]),
    "revert": (("fedora40", "clean-install", "system", True),
               [*SYS, "snapshot-revert", "--domain", "fedora40", "--snapshotname", "clean-install"]),
    "service": (("virtlockd.service", "start"), ["systemctl", "start", "virtlockd.service"]),  # as root
    "wake": ((), None),  # a read: of both connections, which starts a daemon that is idle
}


class Neighbour(MachinePlugin):
    """Another plugin of the platform, asking the libvirt plugin through its app as any plugin may (a container plugin,
    or the MCP plugin for a local agent)."""

    name, title = "neighbour", "Neighbour"

    def wants(self, hook, *args):
        """Not a hook: one of the libvirt plugin's asked through the app."""
        return self.app.ask("libvirt", hook, *args)


class Platform(App):
    """The library's App asking as the platform does: from its page's route, the page named in so many words, or from
    its own code, no one named."""

    NAME, TITLE, ICON = "platform", "Platform", "chip"

    def from_page(self, hook, *args):
        """As the page's route asks a hook."""
        with asking.asking(asking.PAGE):
            return self.ask("libvirt", hook, *args)

    def on_its_own(self, hook, *args):
        """As the app's own code asks a hook."""
        return self.ask("libvirt", hook, *args)


@pytest.fixture(autouse=True)
def user(monkeypatch):
    """The platform runs as a user (uid 1000) here, as in test_plugin."""
    monkeypatch.setattr(linux_mod.os, "geteuid", lambda: 1000, raising=False)


@pytest.fixture
def attached():
    """attach(fake) -> (app, neighbour): the plugin on that stand-in machine, attached with another plugin to an app;
    each let go after the test."""
    held: list[tuple[Platform, Neighbour, object]] = []

    def attach(fake):
        libvirt, neighbour = plugin(fake), Neighbour()
        app = Platform(log=lambda m: None, login=EnvironmentLogin(env={}))
        app.attach(libvirt)
        app.attach(neighbour)
        held.append((app, neighbour, libvirt))
        return app, neighbour
    yield attach
    for app, neighbour, libvirt in held:
        app.detach(neighbour.name)
        app.detach(libvirt.name)


def test_its_changes_are_said_to_be_asked_only_from_its_page_and_its_reads_by_anyone():
    assert set(ASKS) == set(CHANGES)
    assert set(internal.page_only(MACHINE)) == set(CHANGES)  # what the platform reads
    assert internal.plugin_only(MACHINE) == ()
    assert [p for p in internal.problems(MACHINE) if "_ONLY_HOOKS" in p] == []  # each a hook of its own, none in both
    assert set(MACHINE.HOOKS) >= {*CHANGES, *READS}
    for hook in CHANGES:
        assert asking.refusal(MACHINE, hook, asking.PAGE) == ""
        assert asking.refusal(MACHINE, hook, "neighbour") == (f"libvirt's {hook} is asked only from its page, never by "
                                                              "another plugin: neighbour asked it.")
        assert asking.refusal(MACHINE, hook, None).endswith("This ask names no asker: neither the page nor a plugin.")
    for hook in READS:
        assert {asking.refusal(MACHINE, hook, who) for who in (asking.PAGE, "neighbour", None)} == {""}


@pytest.mark.parametrize("groups", [("ciara", "wheel", "libvirt"), ("ciara", "wheel")],
                         ids=["in-the-libvirt-group", "root-through-sudo"])
def test_another_plugin_or_no_one_asking_a_change_runs_nothing_and_its_page_does(groups, attached):
    """With the platform's user in the libvirt group, where a change runs at once as that user, and without, where it
    runs as root through sudo -n: neither asks a password, so nothing stood between a program's ask and the change."""
    fake = FakeLinux(groups=groups)
    app, neighbour = attached(fake)
    for hook in CHANGES:  # each with its confirmation said, as a program would send it
        args, _ = ASKS[hook]
        for ask in (lambda: neighbour.wants(hook, *args), lambda: app.on_its_own(hook, *args)):
            with pytest.raises(asking.AskRefused, match=f"libvirt's {hook} is asked only from its page") as refused:
                ask()
            assert refused.value.status == 403 and refused.value.hook == hook
    assert fake.calls == []  # no command at all: nothing run, nothing read
    assert neighbour.wants("present") is True and neighbour.wants("status")["valid"]  # its reads, as before
    assert fake.changes == []
    root = "libvirt" not in groups
    for hook in CHANGES:  # its page's form, confirmed
        args, command = ASKS[hook]
        answer = app.from_page(hook, *args)
        assert answer["ok"] is True
        if command is None:
            assert answer["said"] == "libvirt read: 4 virtual machines"
            continue
        assert fake.changes[-1] == command
        assert (fake.calls[-1][:3] == SUDO) is (root or hook == "service")  # a service's start is always root's
    assert len(fake.changes) == len(CHANGES) - 1


def test_idle_daemons_and_the_session_are_started_by_the_pages_read_alone(attached):
    """Read now connects to libvirt's idle daemons, which starts them, and virsh starts the user's own session daemon:
    another plugin's ask, or no one's, reads nothing; the page's does."""
    fake = FakeLinux(units="modular-idle", system_daemons=(), session_sockets=(), session_daemons=())
    app, neighbour = attached(fake)
    assert neighbour.wants("status")["valid"] and fake.reads == []  # a status touches no socket
    for ask in (lambda: neighbour.wants("wake"), lambda: app.on_its_own("wake")):
        with pytest.raises(asking.AskRefused, match="libvirt's wake is asked only from its page"):
            ask()
    assert fake.reads == []
    assert app.from_page("wake")["said"] == "libvirt read: 4 virtual machines"
    assert fake.reads == ["system domains,networks,pools", "session domains"]
