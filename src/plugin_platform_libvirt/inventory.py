"""What libvirt holds on one connection (qemu:///system or qemu:///session), read with one script through virsh in the
C locale (its tables' words and dominfo's labels are translated otherwise): `virsh list --all`, each domain's `dominfo`
(its state, vCPUs, memory, autostart, persistence) and `snapshot-list`, `net-list --all` and `pool-list --all
--details`, each command's exit code after it. `read_script` is what runs; `parse` reads its answer into a
`Connection`, each failure in virsh's own words."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from .system import sections

MARK = "== liminal-virsh-read 1"
URIS = {"system": "qemu:///system", "session": "qemu:///session"}
PARTS = ("domains", "networks", "pools")
STATES = ("running", "idle", "paused", "in shutdown", "shut off", "crashed", "pmsuspended", "no state", "dying", "blocked")
ACTIVE = ("running", "idle", "paused", "in shutdown", "pmsuspended", "blocked", "dying")
DENIED = ("permission denied", "authentication unavailable", "authentication failed", "not authorized", "polkit",
          "access denied", "a password is required")
DOWN = ("failed to connect socket", "no such file or directory", "connection refused")
_LIST = re.compile(r"^\s*(\S+)\s+(.+?)\s+(" + "|".join(re.escape(s) for s in STATES) + r")\s*$")
_SNAPSHOT = re.compile(r"^\s*(.+?)\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}):\d{2} ([+-]\d{4})\s+(\S+)\s*$")
_NET = re.compile(r"^\s*(.+?)\s+(active|inactive)\s+(yes|no)\s+(yes|no)\s*$")
_SIZE = r"(-|\d+(?:\.\d+)? \S+)"
_POOL = re.compile(r"^\s*(.+?)\s+(running|inactive|building|degraded|inaccessible)\s+(yes|no)\s+(yes|no)\s+"
                   + _SIZE + r"\s+" + _SIZE + r"\s+" + _SIZE + r"\s*$")


def read_script(virsh: str, connection: str, parts=PARTS) -> str:
    """virsh on one connection: the domains with their dominfo and snapshots, the networks, the storage pools (those of
    `parts`; a daemon left idle is not connected to)."""
    v, u = shlex.quote(virsh), shlex.quote(URIS[connection])
    lines = ["LC_ALL=C; export LC_ALL", f"echo '{MARK}'"]
    if "domains" in parts:
        lines += [f"echo '== list'; {v} -c {u} list --all 2>&1; echo \"== rc $?\"",
                  f"{v} -c {u} list --all --name 2>/dev/null | while IFS= read -r n; do",
                  '  [ -n "$n" ] || continue',
                  f"  echo \"== dominfo $n\"; {v} -c {u} dominfo --domain \"$n\" 2>&1",
                  f"  echo \"== snapshots $n\"; {v} -c {u} snapshot-list --domain \"$n\" 2>&1",
                  "done"]
    if "networks" in parts:
        lines.append(f"echo '== nets'; {v} -c {u} net-list --all 2>&1; echo \"== rc $?\"")
    if "pools" in parts:
        lines.append(f"echo '== pools'; {v} -c {u} pool-list --all --details 2>&1; echo \"== rc $?\"")
    lines.append("echo '== end'")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Snapshot:
    domain: str
    name: str
    created: str = ""  # "2024-05-11 08:01 +0200"
    state: str = ""  # the domain's state when it was taken: running, shutoff, paused, disk-snapshot
    connection: str = "system"


@dataclass(frozen=True)
class Domain:
    name: str
    connection: str = "system"
    id: str = "-"
    state: str = "unknown"
    vcpus: int | None = None
    memory: int | None = None  # KiB in use
    max_memory: int | None = None  # KiB at most
    autostart: bool | None = None
    persistent: bool | None = None
    snapshots: tuple = ()

    @property
    def running(self) -> bool:
        return self.state in ACTIVE


@dataclass(frozen=True)
class Network:
    name: str
    state: str = ""
    autostart: bool = False
    persistent: bool = True
    connection: str = "system"


@dataclass(frozen=True)
class Pool:
    name: str
    state: str = ""
    autostart: bool = False
    persistent: bool = True
    capacity: str = "-"
    allocation: str = "-"
    available: str = "-"
    connection: str = "system"


@dataclass
class Connection:
    """One connection as read: `read` False when it was not (its daemon idle or stopped, or no rights)."""
    name: str = "system"
    read: bool = True
    domains: list = field(default_factory=list)
    networks: list = field(default_factory=list)
    pools: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    denied: bool = False
    down: bool = False

    @property
    def uri(self) -> str:
        return URIS[self.name]

    @property
    def snapshots(self) -> list:
        return [s for d in self.domains for s in d.snapshots]


def words_of(lines) -> str:
    """virsh's error in its own words: its error: lines, without the prefix, joined."""
    said = [re.sub(r"^error:\s*", "", line.strip()) for line in lines if line.strip().lower().startswith("error:")]
    return "; ".join(dict.fromkeys(s for s in said if s)) or " ".join(line.strip() for line in lines if line.strip())


def _number(text: str) -> int | None:
    m = re.match(r"^\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def _yes(text: str) -> bool | None:
    return {"yes": True, "enable": True, "no": False, "disable": False}.get((text or "").strip().lower())


def dominfo(lines: list[str]) -> dict[str, str]:
    """`virsh dominfo`'s "Label:   value" lines, by label."""
    out = {}
    for line in lines:
        k, sep, v = line.partition(":")
        if sep and k.strip() and not line.startswith(" "):
            out[k.strip()] = v.strip()
    return out


def parse(text: str, connection: str = "system") -> Connection:
    """The read script's answer as a Connection."""
    c = Connection(connection)
    if MARK not in (text or ""):
        c.problems.append("the read's answer was not understood")
        return c
    listed: list[tuple[str, str, str]] = []  # (id, name, state) from `list --all`
    info: dict[str, dict[str, str]] = {}
    snaps: dict[str, list[Snapshot]] = {}
    pending, body = None, []

    def failed(lines: list[str]) -> None:
        said = words_of(lines) or "virsh failed"
        low = said.lower()
        c.denied = c.denied or any(d in low for d in DENIED)
        c.down = c.down or any(d in low for d in DOWN)
        if said not in c.problems:
            c.problems.append(said)

    for head, rest, lines in sections(text):
        if head in ("list", "nets", "pools"):
            pending, body = head, lines
        elif head == "rc" and pending:
            if rest != "0":
                failed(body)
            elif pending == "list":
                listed = [(m.group(1), m.group(2).strip(), m.group(3)) for m in map(_LIST.match, body) if m]
            elif pending == "nets":
                c.networks = [Network(m.group(1).strip(), m.group(2), m.group(3) == "yes", m.group(4) == "yes", connection)
                              for m in map(_NET.match, body) if m]
            else:
                c.pools = [Pool(m.group(1).strip(), m.group(2), m.group(3) == "yes", m.group(4) == "yes", m.group(5), m.group(6),
                                m.group(7), connection) for m in map(_POOL.match, body) if m]
            pending = None
        elif head == "dominfo":
            info[rest] = dominfo(lines)
        elif head == "snapshots":
            snaps[rest] = [Snapshot(rest, m.group(1).strip(), f"{m.group(2)} {m.group(3)}", m.group(4), connection)
                           for m in map(_SNAPSHOT.match, lines) if m]
    for id_, name, state in listed:
        d = info.get(name, {})
        c.domains.append(Domain(name, connection, id_, (d.get("State") or state).strip(), _number(d.get("CPU(s)", "")),
                                _number(d.get("Used memory", "")), _number(d.get("Max memory", "")), _yes(d.get("Autostart", "")),
                                _yes(d.get("Persistent", "")), tuple(snaps.get(name, ()))))
    c.domains.sort(key=lambda d: d.name)
    return c
