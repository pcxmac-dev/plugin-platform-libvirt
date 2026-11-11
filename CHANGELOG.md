# Changelog

## 0.2.0 (2026-11-11)

Its API on its page (plugin API 2.2, liminal-libs 1.49.0; the user: "each plugin should reflect the the API its attached
to, and present links that provide documentation, the plugin interface should more or less contain what it already has,
BUT, it should also expose more of what the API is about"). Needs liminal-libs>=1.49.0.

- `apis` (apis.py): three cards, read on libvirt.org, docs.kernel.org, freedesktop.org, man7.org and sudo.ws on
  2026-11-11. **virsh (libvirt)**: libvirt's documentation, virsh's manual, the API reference and its concepts, the
  connection URIs, the QEMU/KVM driver, the domain, snapshot, network and storage XML formats, authentication and access
  control, the releases (12.9.0 the newest); virsh's 13 command sections (domains, snapshots, virtual networks, storage
  pools and its generic commands used; devices, volumes, checkpoints, node devices, interfaces, network ports, secrets,
  network filters not), and 25 commands: the 13 it runs, each beside the libvirt function it is (virConnectListAllDomains,
  virDomainGetInfo, virDomainCreate, virDomainShutdown, virDomainDestroy, virDomainSnapshotCreateXML,
  virDomainRevertToSnapshot …), and the notable others (define, undefine, suspend, save, migrate, console …).
  **libvirt's daemons and services**: the daemons page and each daemon's manual (libvirtd; virtqemud, virtnetworkd,
  virtstoraged; virtlogd, virtlockd, libvirt-guests; the other drivers' daemons), socket activation, systemd, OpenRC,
  sudo -n; the probe's systemctl show, service status, pgrep and id, sudo -n true, and the three ways a service is
  started, none ever stopped. **KVM (the kernel's)**: the kernel's KVM documentation and API; /dev/kvm, the modules and
  the processor's flags, which the plugin only looks at.
- `api_facts()`: what its last look and read said, asking nothing (kept in one dict its copies share, forgotten when
  let go): virsh and its version, each connection's machines, snapshots, networks and pools and its troubles; the
  daemons (monolithic or modular, each connection's state), the rights and whether sudo -n answered, the init system and
  the services; KVM as found.
- Tests: the cards are sound; they name every command the plugin runs (the probe's and the read's as their scripts
  write them, each change's as the stand-in machine was given it, under systemd, OpenRC and SysV scripts, as a member of
  libvirt and through sudo -n) and no other; each virsh command names its libvirt function; the facts ask nothing; with
  LIMINAL_VENDOR_PAGES=1, every address on the cards answers (all did on 2026-11-11).

## 0.1.1 (2026-11-08)

Its icon is libvirt's own mark (the user: "the platform icon matches libvirt's ... libvirt has a can of tuna as an
icon"): its logo's open tin, turned, penguins packed head to toe and the lid rolled back on its key, drawn in the
library's line (liminal-libs 1.34.0's `libvirt`), where it had borrowed the platform's chip. Needs liminal-libs>=1.34.0.

## 0.1.0 (2026-11-08)

The first release (the user: "LXC/LXD plugins and LIBVIRT plugin for virtualization"; of the Linux plugins: "make sure
its compatable with systemd/openrc ... make sure its compatible with major distributions and gentoo linux"), on
liminal-libs 1.30.0:

- virsh on both connections, qemu:///system and the platform's user's own qemu:///session, in the C locale: the
  domains (`virsh list --all`, each one's `dominfo`: state, vCPUs, memory, autostart, persistence) and their
  snapshots (`snapshot-list`), the networks (`net-list --all`), the storage pools (`pool-list --all --details`).
- KVM: /dev/kvm, whether the user may open it (qemu:///session's machines need it), kvm_intel or kvm_amd, the
  processor's vmx or svm; without it the status says how to have it (the module, the firmware).
- Changes through the platform page's confirmed forms (and the command line): start, shut down (ACPI), reboot; force off
  (`virsh destroy`) only once asked a second time (`accept_destroy`; `--yes`); autostart on or off; a snapshot taken
  (`snapshot-create-as --atomic`, named or not, with a description); a snapshot reverted to, asked a second time
  (`accept_revert`).
- libvirt's services, monolithic (libvirtd) or modular (virtqemud, virtnetworkd, virtstoraged), as this machine runs it,
  with virtlogd, virtlockd and libvirt-guests, under systemd, OpenRC (Gentoo's app-emulation/libvirt: libvirtd,
  virtlogd, virtlockd, libvirt-guests) or SysV scripts; a stopped one started only when asked (Start…), none ever
  stopped. An idle daemon (systemd's socket listening, the daemon not running) and the session's own daemon (virsh would
  start one) are not read until asked (Read now…), since connecting starts them.
- The rights over qemu:///system: as the platform's user in the libvirt group (libvirtd on older Debian and Ubuntu),
  plainly as root, else through `sudo -n`; otherwise the problem says how to give them, and the session is read still.
  qemu:///session is always the user's own (none when the platform is root).
- Not installed: how this distribution installs it (Gentoo's emerge and rc-update, Ubuntu, Debian, Fedora, RHEL,
  Arch, openSUSE, Alpine, NixOS, Void).
- Native Linux only (the library's `machines.linux.why_not_native`): on Windows, macOS or in WSL it runs nothing, its
  status says `applies` False, and every hook is refused.
