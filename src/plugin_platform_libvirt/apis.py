"""What the libvirt plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its
attached to, and present links that provide documentation ... it should also expose more of what the API is about"):
virsh and the libvirt API under it, libvirt's daemons (with the init system and the rights they are read and started
through), and KVM, the kernel's. Each part is named with what the plugin does with it, each command with what for and
the libvirt function it is, and the notable others; every address was read on libvirt.org, docs.kernel.org,
freedesktop.org, man7.org and sudo.ws on 2026-11-11."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

VERIFIED = "2026-11-11"
VIRSH = "virsh (libvirt)"
DAEMONS = "libvirt's daemons and services"
KVM = "KVM (the kernel's)"

_V = "https://libvirt.org/manpages/virsh.html"
_M = "https://libvirt.org/manpages/"
_SYSTEMCTL = "https://www.freedesktop.org/software/systemd/man/latest/systemctl.html"
_OPENRC = "https://github.com/OpenRC/openrc/blob/master/user-guide.md"


def _cmd(anchor: str) -> str:
    return f"{_V}#{anchor}"


VIRSH_API = Api(
    name=VIRSH, maker="The libvirt project", kind="command",
    about=("virsh, libvirt's command line: every libvirt API call as a command (the machines, which libvirt calls domains, "
           "their devices, snapshots and checkpoints, the virtual networks, the storage pools and volumes, the host), on a "
           "connection named by a URI. The plugin uses QEMU/KVM's two, qemu:///system (root's daemon) and qemu:///session "
           "(the platform's user's own), always in the C locale; each command beside the libvirt function it is."),
    base="virsh -c qemu:///system | qemu:///session",
    version="libvirt as the distributions ship it (12.9.0, 2026-11-02, is the newest release)",
    auth=("qemu:///system: root, or a member of the libvirt group (libvirt's polkit rule), else root through sudo -n; "
          "qemu:///session: the platform's own user"),
    limits="none (local daemons)",
    costs="",
    links=(
        Link("libvirt documentation", "https://libvirt.org/docs.html", "docs"),
        Link("virsh", _V, "reference"),
        Link("API reference", "https://libvirt.org/html/index.html", "reference"),
        Link("The libvirt API concepts", "https://libvirt.org/api.html", "guide"),
        Link("Connection URIs", "https://libvirt.org/uri.html", "guide"),
        Link("QEMU/KVM driver", "https://libvirt.org/drvqemu.html", "guide"),
        Link("Domain XML format", "https://libvirt.org/formatdomain.html", "spec"),
        Link("Snapshot XML format", "https://libvirt.org/formatsnapshot.html", "spec"),
        Link("Network XML format", "https://libvirt.org/formatnetwork.html", "spec"),
        Link("Storage XML format", "https://libvirt.org/formatstorage.html", "spec"),
        Link("Connection authentication", "https://libvirt.org/auth.html", "auth"),
        Link("Client access control", "https://libvirt.org/acl.html", "auth"),
        Link("Knowledge base", "https://libvirt.org/kbase/index.html", "guide"),
        Link("Releases", "https://libvirt.org/news.html", "changelog"),
        Link("Downloads", "https://libvirt.org/downloads.html", "tool"),
        Link("libvirt/libvirt", "https://gitlab.com/libvirt/libvirt", "source"),
    ),
    areas=(
        Area("Domain commands", "the machines: listed, defined, started, shut down, rebooted, forced off, saved, migrated, "
                                "tuned", _cmd("domain-commands"),
             covered="listed on both connections with their state, vCPUs, memory and autostart; started, shut down, "
                     "rebooted, forced off (asked twice), autostart turned on or off"),
        Area("Snapshot commands", "a machine's snapshots: made, listed, reverted to, deleted", _cmd("snapshot-commands"),
             covered="listed; one made (--atomic); a machine reverted to one (asked twice)"),
        Area("Virtual network commands", "virtual networks: listed, defined, started, their DHCP leases", _cmd("virtual-network-commands"),
             covered="listed with their state, autostart and persistence (qemu:///system)"),
        Area("Storage pool commands", "storage pools: listed, defined, built, started, refreshed", _cmd("storage-pool-commands"),
             covered="listed with their state, capacity and use (qemu:///system)"),
        Area("Generic commands", "the connection, the host and the hypervisor: version, uri, nodeinfo, capabilities",
             _cmd("generic-commands"), covered="virsh's version"),
        Area("Device commands", "disks, interfaces and other devices attached and detached", _cmd("device-commands")),
        Area("Volume commands", "storage volumes: made, cloned, resized, uploaded, deleted", _cmd("volume-commands")),
        Area("Checkpoint commands", "checkpoints for incremental backups", _cmd("checkpoint-commands")),
        Area("Nodedev commands", "the host's devices, and passing them to machines", _cmd("nodedev-commands")),
        Area("Interface commands", "the host's network interfaces", _cmd("interface-commands")),
        Area("Network port commands", "a virtual network's ports", _cmd("network-port-commands")),
        Area("Secret commands", "secrets: passphrases and keys", _cmd("secret-commands")),
        Area("Nwfilter commands", "network filters and their bindings", _cmd("nwfilter-commands")),
    ),
    calls=(
        Call("virsh --version", "virsh's own version", "Generic commands", used="the software fact", docs=_cmd("version")),
        Call("virsh list --all", "every machine, running or not (virConnectListAllDomains)", "Domain commands",
             used="the Machines table, and a change's check that the machine is there", docs=_cmd("list")),
        Call("virsh dominfo --domain NAME", "a machine's state, vCPUs, memory, autostart, persistence (virDomainGetInfo)",
             "Domain commands", used="the Machines table", docs=_cmd("dominfo")),
        Call("virsh snapshot-list --domain NAME", "a machine's snapshots (virDomainListAllSnapshots)", "Snapshot commands",
             used="the Snapshots table; Revert's check", docs=_cmd("snapshot-list")),
        Call("virsh net-list --all", "the virtual networks (virConnectListAllNetworks)", "Virtual network commands",
             used="the Networks table", docs=_cmd("net-list")),
        Call("virsh pool-list --all --details", "the storage pools (virConnectListAllStoragePools)", "Storage pool commands",
             used="the Storage pools table", docs=_cmd("pool-list")),
        Call("virsh start --domain NAME", "a machine started (virDomainCreate)", "Domain commands", used="Start…",
             docs=_cmd("start"), writes=True),
        Call("virsh shutdown --domain NAME", "a machine asked to shut down, ACPI (virDomainShutdown)", "Domain commands",
             used="Shut down…", docs=_cmd("shutdown"), writes=True),
        Call("virsh reboot --domain NAME", "a machine asked to reboot (virDomainReboot)", "Domain commands", used="Reboot…",
             docs=_cmd("reboot"), writes=True),
        Call("virsh destroy --domain NAME", "a machine's power cut (virDomainDestroy)", "Domain commands",
             used="Force off… (asked twice)", docs=_cmd("destroy"), writes=True),
        Call("virsh autostart --domain NAME", "a machine started with the daemon, --disable: not (virDomainSetAutostart)",
             "Domain commands", used="Autostart on or off…", docs=_cmd("autostart"), writes=True),
        Call("virsh snapshot-create-as --domain NAME --atomic", "a snapshot made (virDomainSnapshotCreateXML)",
             "Snapshot commands", used="Snapshot…", docs=_cmd("snapshot-create-as"), writes=True),
        Call("virsh snapshot-revert --domain NAME --snapshotname SNAPSHOT", "a machine put back as it was "
             "(virDomainRevertToSnapshot)", "Snapshot commands", used="Revert… (asked twice)", docs=_cmd("snapshot-revert"),
             writes=True),
        Call("virsh define FILE.xml", "a machine defined from its XML (virDomainDefineXML)", "Domain commands",
             docs=_cmd("define"), writes=True),
        Call("virsh undefine NAME", "a machine's definition removed (virDomainUndefineFlags)", "Domain commands",
             docs=_cmd("undefine"), writes=True),
        Call("virsh suspend NAME", "a machine paused (virDomainSuspend)", "Domain commands", docs=_cmd("suspend"), writes=True),
        Call("virsh save NAME FILE", "a machine's state saved to a file", "Domain commands", docs=_cmd("save"), writes=True),
        Call("virsh migrate NAME URI", "a machine moved to another host (virDomainMigrate3)", "Domain commands",
             docs=_cmd("migrate"), writes=True),
        Call("virsh console NAME", "a machine's serial console", "Domain commands", docs=_cmd("console")),
        Call("virsh snapshot-delete NAME SNAPSHOT", "a snapshot deleted (virDomainSnapshotDelete)", "Snapshot commands",
             docs=_cmd("snapshot-delete"), writes=True),
        Call("virsh net-start NAME", "a virtual network started (virNetworkCreate)", "Virtual network commands",
             docs=_cmd("net-start"), writes=True),
        Call("virsh pool-start NAME", "a storage pool started", "Storage pool commands", docs=_cmd("pool-start"), writes=True),
        Call("virsh vol-list POOL", "a pool's volumes (virStoragePoolListAllVolumes)", "Volume commands", docs=_cmd("vol-list")),
        Call("virsh nodeinfo", "the host's processors and memory (virNodeGetInfo)", "Generic commands", docs=_cmd("nodeinfo")),
        Call("virsh capabilities", "what the host and its hypervisor can do", "Generic commands", docs=_cmd("capabilities")),
    ),
    verified=VERIFIED)

LIBVIRT_DAEMONS = Api(
    name=DAEMONS, maker="The libvirt project; systemd, OpenRC, sudo (theirs)", kind="system",
    about=("libvirt's daemons: the monolithic libvirtd, or the modular ones (virtqemud for QEMU/KVM, virtnetworkd, "
           "virtstoraged and more), with virtlogd, virtlockd and libvirt-guests; each listening on its socket, systemd "
           "starting a daemon when a client connects. The plugin reads their services under systemd, OpenRC or SysV "
           "scripts (as the platform's user), starts one when asked (as root, through sudo -n), never stops one, and "
           "connects to an idle daemon only when asked, since connecting starts it."),
    base="the daemons' services (systemctl, rc-service, service), their sockets in /run/libvirt and $XDG_RUNTIME_DIR",
    version=("monolithic or modular, as the distribution sets it up (libvirt builds both; its client still prefers the "
             "monolithic daemon)"),
    auth="reading: the platform's user; starting a service: root, through sudo -n alone (never a password asked)",
    limits="none (local)",
    costs="",
    links=(
        Link("Libvirt daemons", "https://libvirt.org/daemons.html", "docs"),
        Link("libvirtd", _M + "libvirtd.html", "reference"),
        Link("virtqemud", _M + "virtqemud.html", "reference"),
        Link("Manual pages", _M + "index.html", "reference"),
        Link("systemctl", _SYSTEMCTL, "reference"),
        Link("systemd.socket", "https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html", "reference"),
        Link("OpenRC user guide", _OPENRC, "guide"),
        Link("libvirt on Gentoo", "https://wiki.gentoo.org/wiki/Libvirt", "guide"),
        Link("sudo (its -n)", "https://www.sudo.ws/docs/man/sudo.man/", "auth"),
        Link("os-release", "https://www.freedesktop.org/software/systemd/man/latest/os-release.html", "reference"),
    ),
    areas=(
        Area("Monolithic or modular", "libvirtd alone, or one daemon a driver", "https://libvirt.org/daemons.html",
             covered="which this machine has, and the daemon serving each part (machines, networks, pools)"),
        Area("libvirtd", "the monolithic daemon: every driver in one", _M + "libvirtd.html", covered="its service read, started"),
        Area("virtqemud", "the QEMU/KVM driver's daemon: the machines", _M + "virtqemud.html",
             covered="its service and socket read, started; the session's own looked for"),
        Area("virtnetworkd", "the virtual networks' daemon", _M + "virtnetworkd.html", covered="its service read, started"),
        Area("virtstoraged", "the storage pools' daemon", _M + "virtstoraged.html", covered="its service read, started"),
        Area("virtlogd", "QEMU's logs", _M + "virtlogd.html", covered="its service read, started"),
        Area("virtlockd", "the disk images' locks", _M + "virtlockd.html", covered="its service read, started"),
        Area("libvirt-guests", "the machines at the host's shutdown: suspended or shut down, then back", _M + "libvirt-guests.html",
             covered="its service read, started"),
        Area("Sockets", "a daemon started by systemd when a client connects", "https://libvirt.org/daemons.html",
             covered="an idle socket seen and not connected to unless asked (Read now)"),
        Area("Init systems", "systemd, OpenRC or SysV scripts", _SYSTEMCTL,
             covered="the units' states read (systemctl show; OpenRC's state files; service NAME status)"),
        Area("Users, groups and root", "the user, its groups (libvirt), root through sudo -n",
             "https://www.sudo.ws/docs/man/sudo.man/", covered="the rights fact; sudo -n true asked (kept 5 minutes)"),
        Area("The other drivers' daemons", "virtnodedevd, virtsecretd, virtinterfaced, virtnwfilterd, virtproxyd",
             _M + "virtnodedevd.html"),
    ),
    calls=(
        Call("systemctl show -p Id,LoadState,ActiveState,SubState,UnitFileState,Description UNITS", "the units' states",
             "Init systems", used="the Daemons table", docs=_SYSTEMCTL),
        Call("systemctl start UNIT", "a unit started (as root)", "Init systems", used="Start… a daemon's service",
             docs=_SYSTEMCTL, writes=True),
        Call("rc-service NAME start", "an OpenRC service started (as root)", "Init systems", used="Start… under OpenRC",
             docs=_OPENRC, writes=True),
        Call("service NAME status", "a SysV script's status", "Init systems", used="the Daemons table (SysV)"),
        Call("service NAME start", "a SysV script started (as root)", "Init systems", used="Start… under SysV scripts",
             writes=True),
        Call("pgrep -u 0 -x DAEMON", "whether a daemon runs as root (or as the user: the session's)", "Monolithic or modular",
             used="the daemons' facts", docs="https://man7.org/linux/man-pages/man1/pgrep.1.html"),
        Call("id -nG", "the user's groups", "Users, groups and root", used="the rights fact",
             docs="https://man7.org/linux/man-pages/man1/id.1.html"),
        Call("sudo -n true", "whether root is had without a password", "Users, groups and root", used="the rights fact",
             docs="https://www.sudo.ws/docs/man/sudo.man/"),
        Call("systemctl stop UNIT", "a unit stopped", "Init systems", docs=_SYSTEMCTL, writes=True),
        Call("systemctl enable --now virtqemud.socket", "a modular daemon's socket enabled and started", "Sockets",
             docs=_SYSTEMCTL, writes=True),
        Call("rc-update add libvirtd default", "libvirtd added to OpenRC's default runlevel", "Init systems", docs=_OPENRC,
             writes=True),
    ),
    verified=VERIFIED)

KERNEL_KVM = Api(
    name=KVM, maker="The Linux kernel (KVM)", kind="kernel",
    about=("KVM, the kernel's own virtualization, which QEMU uses under libvirt: /dev/kvm, the kvm module with kvm_intel or "
           "kvm_amd, the processor's vmx or svm. The plugin only looks: whether /dev/kvm is there and the platform's user "
           "may open it, which modules are loaded, and whether the processor has virtualization (off in the firmware when "
           "it shows neither flag)."),
    base="/dev/kvm, /sys/module/kvm*, /proc/cpuinfo",
    version="the running kernel's",
    auth="/dev/kvm's permissions (the kvm group on most distributions)",
    limits="none",
    costs="",
    links=(
        Link("KVM (the kernel's documentation)", "https://docs.kernel.org/virt/kvm/index.html", "docs"),
        Link("The KVM API", "https://docs.kernel.org/virt/kvm/api.html", "reference"),
        Link("KVM", "https://www.linux-kvm.org/page/Main_Page", "guide"),
    ),
    areas=(
        Area("/dev/kvm", "the device every KVM user opens", "https://docs.kernel.org/virt/kvm/api.html",
             covered="whether it is there, and readable and writable by the platform's user"),
        Area("Modules", "kvm, and kvm_intel or kvm_amd", "https://docs.kernel.org/virt/kvm/index.html",
             covered="which are loaded (/sys/module)"),
        Area("Processor flags", "vmx (Intel VT-x) or svm (AMD-V)", "https://www.linux-kvm.org/page/Main_Page",
             covered="whether the processor shows either (/proc/cpuinfo)"),
        Area("System, VM and vCPU ioctls", "VMs and their vCPUs made and run (QEMU's, through libvirt)",
             "https://docs.kernel.org/virt/kvm/api.html"),
    ),
    calls=(
        Call("[ -c /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]", "whether /dev/kvm is there and usable", "/dev/kvm",
             used="the KVM fact", docs="https://docs.kernel.org/virt/kvm/api.html"),
        Call("[ -d /sys/module/kvm_intel ] (kvm, kvm_amd)", "whether the modules are loaded", "Modules", used="the KVM fact",
             docs="https://docs.kernel.org/virt/kvm/index.html"),
        Call("grep -owE 'vmx|svm' /proc/cpuinfo", "the processor's virtualization flag", "Processor flags",
             used="the KVM fact (and how to have it when it is missing)"),
        Call("ioctl KVM_CREATE_VM", "a VM made on /dev/kvm (QEMU's)", "System, VM and vCPU ioctls",
             docs="https://docs.kernel.org/virt/kvm/api.html", writes=True),
    ),
    verified=VERIFIED)

APIS = (VIRSH_API, LIBVIRT_DAEMONS, KERNEL_KVM)
