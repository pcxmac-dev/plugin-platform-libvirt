# plugin-platform-libvirt

libvirt for Liminal: the virtual machines libvirt runs with QEMU/KVM on the native Linux machine the platform runs
on (qemu:///system's and the user's qemu:///session's), their snapshots, the networks, the storage pools, KVM and
libvirt's services; changed only when asked.

The user's words (2026-11-08): "LXC/LXD plugins and LIBVIRT plugin for virtualization"; of the Linux plugins: "make
sure its compatable with systemd/openrc ... make sure its compatible with major distributions and gentoo linux"; "the
scope of linux administration is only on native linux O/S"; "it's not for administrating WSL instances".

## What it does

A machine plugin of the platform (`liminal_libs.machines.MachinePlugin`, plugin API 2.1, its icon the chip), through
the library's `machines.linux.Shell` on this machine:

- **Read** through virsh in the C locale (its tables and dominfo's labels are translated otherwise), on both
  connections: **qemu:///system** (root's daemon: the machines most installs make) and **qemu:///session** (the
  platform's user's own: GNOME Boxes', virt-manager's user session):
  - the virtual machines (`virsh list --all`; each one's `dominfo`: state, vCPUs, memory in use and at most,
    autostart, persistent or transient) and their snapshots (`snapshot-list`: taken when, the state then);
  - qemu:///system's networks (`net-list --all`) and storage pools (`pool-list --all --details`: capacity,
    allocation, what is free).
- **KVM**: `/dev/kvm` and whether the user may open it (qemu:///session's machines run as the user: the kvm group),
  the kvm_intel or kvm_amd module, the processor's vmx or svm. Without it the status says how to have it (the module,
  or virtualization turned on in the firmware) since the machines would be emulated, slowly.
- **Changed** only when asked, through the platform page's confirmed forms or the command line:
  - start, shut down (ACPI: the machine's own system is asked, and may take a while or ignore it), reboot;
  - force off (`virsh destroy`: its power cut at once): asked a second time (`accept_destroy`);
  - autostart on or off (the Autostart cell of each persistent machine is its switch);
  - a snapshot taken (`virsh snapshot-create-as --atomic`, named or named by libvirt, with a description);
  - a snapshot reverted to (`virsh snapshot-revert`): asked a second time, since what changed since is lost
    (`accept_revert`).
- **libvirt's services** (Daemons) with their state and whether they start at boot, as this machine runs libvirt:
  monolithic (`libvirtd`) or modular (`virtqemud`, `virtnetworkd`, `virtstoraged`, each with its socket), with
  `virtlogd`, `virtlockd` and `libvirt-guests`. The mode is what runs or is set to start, else the distribution's way
  (Fedora, RHEL and openSUSE modular; Debian, Ubuntu, Arch and Gentoo libvirtd). A stopped one is started only when
  asked (Start…); none is ever stopped.

  | | systemd | OpenRC / SysV scripts |
  |---|---|---|
  | monolithic | `libvirtd.service`, `libvirtd.socket` | `libvirtd` (Gentoo's app-emulation/libvirt, Alpine) |
  | modular | `virtqemud`, `virtnetworkd`, `virtstoraged` (`.service`, `.socket`) | the same names, when installed |
  | both | `virtlogd`, `virtlockd`, `libvirt-guests` | `virtlogd`, `virtlockd`, `libvirt-guests` |

  The init system is told as the library's services scan tells it (systemd when `/run/systemd/system` is there;
  OpenRC with `rc-status` and `/run/openrc` or openrc-init as PID 1; else SysV scripts through `service`).
- **Nothing is started by a read.** A daemon that is idle (systemd's socket listening, the daemon not running) would be
  started by the first client, and virsh starts the user's own session daemon when none runs; so those are read only
  once asked (**Read now…**), and from then on until the platform lets the plugin go. A modular daemon that is idle
  keeps its part (the networks, the storage pools) unread too. A stopped one is said as the problem, Start… beside it.

## The rights

- qemu:///system: as the platform's user when it is in `libvirt` (libvirt's polkit rule lets its members manage the
  system's machines; `libvirtd` on older Debian and Ubuntu; on Gentoo with USE=policykit, or with `unix_sock_group` set
  in libvirtd.conf), plainly when the platform is root, else as root through `sudo -n` (never a password asked). None
  of these: the problem says how to give them (`sudo usermod -aG libvirt USER` and a new login; root; sudo without a
  password), and qemu:///session is read still. A group given after this login is named as such.
- qemu:///session: always the user's own, never through sudo; none when the platform runs as root.
- Starting a service needs root (`systemctl start`, `rc-service ... start`, `service ... start`): through `sudo -n`
  when the platform is not root; refused, it says the command to run.

## Distributions

Not installed (no virsh), the status says how this distribution installs it (from `/etc/os-release`'s ID and
ID_LIKE): Gentoo (`emerge --ask app-emulation/libvirt app-emulation/qemu`, USE=policykit for the group;
`rc-update add libvirtd default` under OpenRC, `systemctl enable --now libvirtd` under systemd), Ubuntu (`apt install
qemu-kvm libvirt-daemon-system libvirt-clients`) and its derivatives, Debian (`apt install qemu-system libvirt-clients
libvirt-daemon-system`), Fedora (`dnf install @virtualization` and the modular sockets), RHEL and its rebuilds, Arch
(`pacman -S libvirt qemu-base dnsmasq`, `libvirtd.socket`), openSUSE (the kvm_server pattern), Alpine (`apk add
libvirt-daemon`, `rc-update add libvirtd`), NixOS (`virtualisation.libvirtd.enable`), Void (`xbps-install libvirt
qemu`).

## Native Linux only

On Windows, on macOS and inside a WSL distribution (its kernel's release names Microsoft or WSL, or WSL's variables
are set) it runs no command at all: its status says why with `applies` False, so the platform shows it as not for
this machine and offers no setup; every hook is refused. The check is the library's (`machines.linux.why_not_native`).

## Its hooks

`present`, `status` (the facts; `tables`: Virtual machines, Snapshots, Networks, Storage pools, Daemons; `forms`;
`actions`), `power(name, action, connection, accept_destroy)` (`start`, `shutdown`, `reboot`, `destroy`),
`autostart(name, on, connection)`, `snapshot(name, snapshot, description, connection)`, `revert(name, snapshot,
connection, accept_revert)`, `service(unit, action)` (`start` only), `wake()` (Read now), `run(*args, connection)`
(virsh with these arguments). `connection` is `system` (the default) or `session`. A refusal (an unknown machine or
snapshot, a change not accepted yet) is a `ValueError` naming the argument that accepts it, which the page asks as a
second confirmation.

## From the command line

```
python -m plugin_platform_libvirt status              # the status as JSON; --wake reads idle daemons too
python -m plugin_platform_libvirt wake
python -m plugin_platform_libvirt start win11
python -m plugin_platform_libvirt shutdown fedora40
python -m plugin_platform_libvirt destroy fedora40 --yes
python -m plugin_platform_libvirt autostart win11 on
python -m plugin_platform_libvirt snapshot fedora40 before-update --description "before dnf upgrade"
python -m plugin_platform_libvirt revert fedora40 before-update --yes
python -m plugin_platform_libvirt start boxes-alpine --session
python -m plugin_platform_libvirt service libvirtd.service start
python -m plugin_platform_libvirt run -- domifaddr fedora40
```

Forcing off and reverting are refused until asked again with `--yes`, as the page asks a second time.
