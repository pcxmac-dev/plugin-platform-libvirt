"""What this Linux machine has for libvirt, read with one script as the platform's own user (no root, nothing
started): who the platform runs as and its groups (the process's, and the group database's: a group given after this
login is not the process's yet), the init system (systemd, OpenRC, or SysV scripts through the service command, told
as the library's services scan tells them), virsh and its version, the distribution (/etc/os-release), KVM (/dev/kvm,
whether this user may open it, the kvm, kvm_intel and kvm_amd modules, the processor's vmx or svm), the daemons'
sockets and processes for qemu:///system (root's) and for this user's qemu:///session, and each service of libvirt's
the init system knows (systemd's units: libvirtd, or the modular virtqemud, virtnetworkd, virtstoraged, with virtlogd,
virtlockd and libvirt-guests; OpenRC's /etc/init.d scripts, Gentoo's libvirtd among them, their state and runlevels;
the SysV scripts' status). `parse` reads that into a `Probe`; `install_words` says how this distribution installs it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from liminal_libs.machines.services import INIT_WORDS

MARK = "== liminal-libvirt-probe 1"
DAEMONS = ("libvirtd", "virtqemud", "virtnetworkd", "virtstoraged")
SYSTEM_SOCKETS = ("libvirt-sock", "virtqemud-sock", "virtnetworkd-sock", "virtstoraged-sock")
SESSION_SOCKETS = ("libvirt-sock", "virtqemud-sock")
UP = ("running", "listening", "on", "starting")
STARTABLE = ("stopped", "failed", "inactive")
GROUPS = ("libvirt", "libvirtd")  # libvirtd: older Debian and Ubuntu


@dataclass(frozen=True)
class Known:
    """A service of libvirt's as an init system names it: `inits` the ones that do (systemd; openrc and sysvinit share
    /etc/init.d's names), `mode` whose it is: monolithic (libvirtd), modular (virtqemud...), * either."""
    name: str
    mode: str
    inits: tuple[str, ...]
    role: str
    daemon: bool = False


SYSTEMD = ("systemd",)
RC = ("openrc", "sysvinit")
SOCKET = "its socket: systemd starts the daemon when a client connects"
KNOWN = (
    Known("libvirtd.service", "monolithic", SYSTEMD, "libvirt's daemon: every driver in one", daemon=True),
    Known("libvirtd.socket", "monolithic", SYSTEMD, SOCKET),
    Known("virtqemud.service", "modular", SYSTEMD, "the QEMU/KVM driver's daemon: the virtual machines", daemon=True),
    Known("virtqemud.socket", "modular", SYSTEMD, SOCKET),
    Known("virtnetworkd.service", "modular", SYSTEMD, "the networks' daemon", daemon=True),
    Known("virtnetworkd.socket", "modular", SYSTEMD, SOCKET),
    Known("virtstoraged.service", "modular", SYSTEMD, "the storage pools' daemon", daemon=True),
    Known("virtstoraged.socket", "modular", SYSTEMD, SOCKET),
    Known("virtlogd.service", "*", SYSTEMD, "QEMU's logs (virtlogd)"),
    Known("virtlogd.socket", "*", SYSTEMD, "virtlogd's socket"),
    Known("virtlockd.service", "*", SYSTEMD, "the disk images' locks (virtlockd)"),
    Known("libvirt-guests.service", "*", SYSTEMD, "the virtual machines at the host's shutdown: suspended or shut down, then back"),
    Known("libvirtd", "monolithic", RC, "libvirt's daemon: every driver in one", daemon=True),
    Known("virtqemud", "modular", RC, "the QEMU/KVM driver's daemon: the virtual machines", daemon=True),
    Known("virtnetworkd", "modular", RC, "the networks' daemon", daemon=True),
    Known("virtstoraged", "modular", RC, "the storage pools' daemon", daemon=True),
    Known("virtlogd", "*", RC, "QEMU's logs (virtlogd)"),
    Known("virtlockd", "*", RC, "the disk images' locks (virtlockd)"),
    Known("libvirt-guests", "*", RC, "the virtual machines at the host's shutdown: suspended or shut down, then back"),
)
SYSTEMD_UNITS = tuple(k.name for k in KNOWN if "systemd" in k.inits)
RC_NAMES = tuple(k.name for k in KNOWN if "systemd" not in k.inits)

# POSIX sh, as the platform's user: nothing in it needs root or starts anything
SCRIPT = r"""LC_ALL=C; export LC_ALL
echo '@MARK@'
uid=$(id -u 2>/dev/null)
echo "== user $(id -un 2>/dev/null) $uid"
echo "== groups $(id -nG 2>/dev/null)"
echo "== member $(id -nG "$(id -un 2>/dev/null)" 2>/dev/null)"
p1=$(cat /proc/1/comm 2>/dev/null || echo unknown)
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then init=systemd
elif command -v rc-status >/dev/null 2>&1 && { [ -d /run/openrc ] || [ "$p1" = openrc-init ]; }; then init=openrc
elif command -v service >/dev/null 2>&1; then init=sysvinit
else init=none; fi
echo "== init $init $p1"
v=$(command -v virsh 2>/dev/null)
if [ -n "$v" ]; then
  echo "== tool virsh $v"
  echo "== version virsh $("$v" --version 2>/dev/null | head -n 1)"
fi
echo '== os'
if [ -r /etc/os-release ]; then grep -E '^(ID|ID_LIKE|NAME|PRETTY_NAME|VERSION_ID)=' /etc/os-release; fi
k=
if [ -c /dev/kvm ]; then k="$k dev"; fi
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then k="$k rw"; fi
for m in kvm kvm_intel kvm_amd; do
  if [ -d "/sys/module/$m" ]; then k="$k $m"; fi
done
f=$(grep -m 1 -owE 'vmx|svm' /proc/cpuinfo 2>/dev/null | head -n 1)
if [ -n "$f" ]; then k="$k cpu:$f"; fi
echo "== kvm$k"
for s in @SYSTEM_SOCKETS@; do
  if [ -S "/run/libvirt/$s" ] || [ -S "/var/run/libvirt/$s" ]; then echo "== socket system $s"; fi
done
rt=${XDG_RUNTIME_DIR:-/run/user/$uid}
for s in @SESSION_SOCKETS@; do
  if [ "$uid" != 0 ] && [ -S "$rt/libvirt/$s" ]; then echo "== socket session $s"; fi
done
for d in @DAEMONS@; do
  if pgrep -u 0 -x "$d" >/dev/null 2>&1; then echo "== daemon system $d"; fi
  if [ "$uid" != 0 ] && pgrep -u "$uid" -x "$d" >/dev/null 2>&1; then echo "== daemon session $d"; fi
done
case $init in
systemd)
  echo '== units'
  systemctl show -p Id,LoadState,ActiveState,SubState,UnitFileState,Description @UNITS@ 2>/dev/null
  ;;
openrc)
  echo '== openrc'
  for n in @RC@; do
    [ -e "/etc/init.d/$n" ] || continue
    st=stopped
    for d in started starting stopping inactive failed; do
      if [ -e "/run/openrc/$d/$n" ]; then st=$d; fi
    done
    lv=
    for r in /etc/runlevels/*; do
      if [ -e "$r/$n" ]; then lv="$lv${lv:+,}${r##*/}"; fi
    done
    echo "$n $st ${lv:--}"
  done
  ;;
sysvinit)
  echo '== sysv'
  for n in @RC@; do
    [ -e "/etc/init.d/$n" ] || continue
    service "$n" status >/dev/null 2>&1
    echo "$n $?"
  done
  ;;
esac
echo '== end'
"""
PROBE = (SCRIPT.replace("@MARK@", MARK).replace("@SYSTEM_SOCKETS@", " ".join(SYSTEM_SOCKETS))
         .replace("@SESSION_SOCKETS@", " ".join(SESSION_SOCKETS)).replace("@DAEMONS@", " ".join(DAEMONS))
         .replace("@UNITS@", " ".join(SYSTEMD_UNITS)).replace("@RC@", " ".join(RC_NAMES)))

OPENRC_STATES = {"started": "running", "starting": "starting", "stopping": "stopping", "inactive": "inactive",
                 "failed": "failed", "stopped": "stopped"}


@dataclass(frozen=True)
class Unit:
    """A service as its init system says it is: `state` running | listening (a socket) | on (done, staying on) |
    starting | stopping | failed | stopped | inactive | masked | unknown; `boot` systemd's unit file state (enabled,
    disabled, static...) or OpenRC's runlevels."""
    name: str
    state: str
    boot: str = ""
    description: str = ""
    known: Known | None = None

    @property
    def up(self) -> bool:
        return self.state in UP

    @property
    def startable(self) -> bool:
        return self.state in STARTABLE

    @property
    def enabled(self) -> bool:
        return bool(self.boot) and self.boot not in ("disabled", "static", "masked", "indirect", "generated", "transient", "-")

    @property
    def role(self) -> str:
        return self.known.role if self.known else self.description


@dataclass(frozen=True)
class Probe:
    """What the probe found; `problem` when its answer was not the probe's."""
    user: str = ""
    uid: int = -1
    groups: frozenset = frozenset()  # the platform process's own
    member: frozenset = frozenset()  # the user's in the group database
    init: str = "unknown"
    pid1: str = ""
    virsh: str = ""  # its path; "" when it is not installed
    version: str = ""
    os: dict = field(default_factory=dict)
    kvm: frozenset = frozenset()  # dev, rw, kvm, kvm_intel, kvm_amd, cpu:vmx, cpu:svm
    sockets: dict = field(default_factory=dict)  # system | session -> the sockets there (virtqemud-sock...)
    daemons: dict = field(default_factory=dict)  # system | session -> the daemons running (virtqemud...)
    units: dict = field(default_factory=dict)  # name -> Unit, those the init system has
    problem: str = ""

    @property
    def root(self) -> bool:
        return self.uid == 0


def sections(text: str) -> list[tuple[str, str, list[str]]]:
    """`== head rest` headed sections of a script's answer: (head, rest, the lines beneath)."""
    out: list[tuple[str, str, list[str]]] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if line.startswith("== "):
            head, _, rest = line[3:].partition(" ")
            out.append((head, rest.strip(), []))
        elif out:
            out[-1][2].append(line)
    return out


def _systemd_state(load: str, active: str, sub: str) -> str:
    if load in ("not-found", "") or load.startswith("error") or load == "bad-setting":
        return "absent"
    if load == "masked":
        return "masked"
    if active == "active":
        return {"running": "running", "listening": "listening", "exited": "on"}.get(sub, "on")
    if active in ("activating", "reloading"):
        return "starting"
    if active == "deactivating":
        return "stopping"
    if active == "failed":
        return "failed"
    return "stopped"


def systemd_units(lines: list[str], known=KNOWN) -> dict[str, Unit]:
    """`systemctl show -p Id,...` blocks (an empty line between units): the units loaded, by name."""
    by = {k.name: k for k in known if "systemd" in k.inits}
    out: dict[str, Unit] = {}
    block: dict[str, str] = {}

    def flush() -> None:
        name = block.get("Id", "")
        if name:
            state = _systemd_state(block.get("LoadState", ""), block.get("ActiveState", ""), block.get("SubState", ""))
            if state != "absent":
                out[name] = Unit(name, state, block.get("UnitFileState", ""), block.get("Description", ""), by.get(name))
        block.clear()

    for line in lines:
        if not line.strip():
            flush()
        elif "=" in line:
            k, _, v = line.partition("=")
            if k == "Id" and block.get("Id"):
                flush()
            block[k.strip()] = v.strip()
    flush()
    return out


def parse(text: str, known=KNOWN) -> Probe:
    """The probe's answer as a Probe; one that is not the probe's is a problem, never a guess."""
    if MARK not in (text or ""):
        return Probe(problem="the probe's answer was not understood")
    found: dict = {"os": {}, "units": {}}
    sockets: dict = {"system": set(), "session": set()}
    daemons: dict = {"system": set(), "session": set()}
    for head, rest, body in sections(text):
        if head == "user":
            name, _, uid = rest.partition(" ")
            found["user"], found["uid"] = name, int(uid) if uid.strip().isdecimal() else -1
        elif head in ("groups", "member"):
            found[head] = frozenset(rest.split())
        elif head == "init":
            init, _, pid1 = rest.partition(" ")
            found["init"], found["pid1"] = init or "unknown", pid1.strip()
        elif head == "tool":
            tool, _, path = rest.partition(" ")
            if tool == "virsh" and path.strip():
                found["virsh"] = path.strip()
        elif head == "version":
            tool, _, said = rest.partition(" ")
            if tool == "virsh":
                found["version"] = said.strip()
        elif head == "os":
            for line in body:
                k, _, v = line.partition("=")
                if k.strip() and v:
                    found["os"][k.strip()] = v.strip().strip('"').strip("'")
        elif head == "kvm":
            found["kvm"] = frozenset(rest.split())
        elif head in ("socket", "daemon"):
            where, _, name = rest.partition(" ")
            if where in ("system", "session") and name.strip():
                (sockets if head == "socket" else daemons)[where].add(name.strip())
        elif head == "units":
            found["units"].update(systemd_units(body, known))
        elif head in ("openrc", "sysv"):
            init_known = {k.name: k for k in known if ("openrc" if head == "openrc" else "sysvinit") in k.inits}
            for line in body:
                words = line.split()
                if len(words) < 2 or words[0] not in init_known:
                    continue
                if head == "openrc":
                    state, boot = OPENRC_STATES.get(words[1], "unknown"), (words[2] if len(words) > 2 and words[2] != "-" else "")
                else:
                    state, boot = {"0": "running", "3": "stopped"}.get(words[1], "unknown"), ""
                found["units"][words[0]] = Unit(words[0], state, boot, "", init_known[words[0]])
    return Probe(user=found.get("user", ""), uid=found.get("uid", -1), groups=found.get("groups", frozenset()),
                 member=found.get("member", frozenset()), init=found.get("init", "unknown"), pid1=found.get("pid1", ""),
                 virsh=found.get("virsh", ""), version=found.get("version", ""), os=found["os"],
                 kvm=found.get("kvm", frozenset()), sockets={k: frozenset(v) for k, v in sockets.items()},
                 daemons={k: frozenset(v) for k, v in daemons.items()}, units=found["units"])


def init_words(p: Probe) -> str:
    """The init system in words, with PID 1 when it says more (openrc-init, a container's)."""
    words = INIT_WORDS.get(p.init, p.init)
    return words + (f" (PID 1: {p.pid1})" if p.pid1 and p.pid1 not in ("systemd", "unknown", "") else "")


def kvm_words(p: Probe) -> tuple[str, bool]:
    """KVM in words, and whether it is there (a virtual machine without it is emulated: slow)."""
    module = next((m for m in ("kvm_intel", "kvm_amd") if m in p.kvm), "")
    flag = next((f[4:] for f in p.kvm if f.startswith("cpu:")), "")
    user = p.user or "the platform's user"
    if "dev" in p.kvm:
        loaded = f"{module} loaded" if module else "built into the kernel"
        mine = (f"{user} may open it" if "rw" in p.kvm else
                f"{user} may not open it, which qemu:///session's machines need: the kvm group (sudo usermod -aG kvm {user})")
        return f"/dev/kvm present ({loaded}); {mine}", True
    if flag:
        want = "kvm_intel" if flag == "vmx" else "kvm_amd"
        return (f"no /dev/kvm, though the processor has {flag}: load {want} (sudo modprobe {want}), or turn virtualization "
                "on in the firmware (BIOS/UEFI); without it the machines are emulated, slowly"), False
    return ("no /dev/kvm, and the processor shows neither vmx nor svm: virtualization is off in the firmware (BIOS/UEFI), "
            "or this machine is itself virtual without nested virtualization; without it the machines are emulated, slowly"), False


# -- the distribution, and how it installs libvirt -----------------------------------------------------------------
FAMILIES = {"gentoo": "gentoo", "funtoo": "gentoo", "calculate": "gentoo", "alpine": "alpine", "nixos": "nixos",
            "void": "void", "ubuntu": "ubuntu", "debian": "debian", "fedora": "fedora", "rhel": "rhel", "centos": "rhel",
            "rocky": "rhel", "almalinux": "rhel", "arch": "arch", "opensuse": "opensuse", "suse": "opensuse",
            "opensuse-tumbleweed": "opensuse", "opensuse-leap": "opensuse", "sles": "opensuse"}


def family(os_release: dict) -> str:
    """The distribution's family: its own ID first, then those it is like, nearest first (Mint: ubuntu; Rocky: rhel)."""
    for word in [os_release.get("ID", ""), *os_release.get("ID_LIKE", "").split()]:
        if word.lower() in FAMILIES:
            return FAMILIES[word.lower()]
    return ""


def distribution(p: Probe) -> str:
    return p.os.get("PRETTY_NAME") or p.os.get("NAME") or "a Linux distribution /etc/os-release does not name"


INSTALL = {
    "gentoo": ("emerge --ask app-emulation/libvirt app-emulation/qemu (USE=policykit for the libvirt group), then under "
               "OpenRC rc-update add libvirtd default and rc-service libvirtd start, under systemd systemctl enable --now libvirtd"),
    "ubuntu": "sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients",
    "debian": "sudo apt install --no-install-recommends qemu-system libvirt-clients libvirt-daemon-system",
    "fedora": ("sudo dnf install @virtualization, then sudo systemctl enable --now virtqemud.socket virtnetworkd.socket "
               "virtstoraged.socket (Fedora's modular daemons)"),
    "rhel": ("sudo dnf install qemu-kvm libvirt virt-install, then sudo systemctl enable --now virtqemud.socket "
             "virtnetworkd.socket virtstoraged.socket"),
    "arch": "sudo pacman -S libvirt qemu-base dnsmasq, then sudo systemctl enable --now libvirtd.socket",
    "opensuse": "sudo zypper install -t pattern kvm_server kvm_tools",
    "alpine": "apk add libvirt-daemon qemu-system-x86_64, then rc-update add libvirtd and rc-service libvirtd start",
    "nixos": "virtualisation.libvirtd.enable = true; in configuration.nix",
    "void": "xbps-install libvirt qemu, then ln -s /etc/sv/libvirtd /etc/sv/virtlogd /etc/sv/virtlockd /var/service",
}
INSTALL_ELSE = "libvirt and QEMU from this distribution's packages (libvirt.org/downloads.html)"


def install_words(p: Probe) -> str:
    how = INSTALL.get(family(p.os), INSTALL_ELSE)
    user = p.user or "your user"
    return (f"libvirt is not installed (no virsh): {how}; then add {user} to libvirt (sudo usermod -aG libvirt {user}) "
            "and log in again")


_VERSION = re.compile(r"^\d+(\.\d+)+")


def looks_like_version(text: str) -> bool:
    return bool(_VERSION.match((text or "").strip()))
