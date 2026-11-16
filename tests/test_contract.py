"""Every plugin here conforms to the class contract (plugin API 2.2): liminal_libs.sources.conformance, read
from the plugin alone (nothing runs); its icon is one the library serves (icons.js)."""
from __future__ import annotations

import re
from pathlib import Path

import liminal_libs
import plugin_platform_libvirt as module
from liminal_libs.sources.conformance import assert_module_conforms


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert found and all(p.api == "2.2" and not p.is_record for p in found)
    assert {p.SYSTEM for p in found} == {"platform"} and {p.KIND for p in found} == {"machine"}
    assert {p.ICON for p in found} == {"libvirt"}  # its own mark, not the platform's chip (the user, 2026-11-08)
    icons = (Path(liminal_libs.__file__).parent / "ui" / "static" / "icons.js").read_text(encoding="utf-8")
    assert {p.ICON for p in found} <= set(re.findall(r"(?m)^\s*([a-z]+):\s*'", icons))


def test_it_is_drawn_under_the_platforms_virtualization_plugins():
    """Its section of the platform's list (liminal-platform 0.26.0; the user, 2026-11-15: "platform needs a virtualization
    plugins section"; "just like cloud plugins"): Virtualization plugins, beside the machine's own, the OS and the cloud
    plugins."""
    assert {p.SECTION for p in assert_module_conforms(module)} == {"virtualization"}
