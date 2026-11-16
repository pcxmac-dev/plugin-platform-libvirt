"""Nothing in these tests starts a process or reaches the network: every command goes to a stand-in runner handed to
the plugin, and a process started or a connection made anyway fails the test."""
from __future__ import annotations

import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_processes_and_no_network(monkeypatch):
    def started(*a, **k):
        raise AssertionError("a test started a process")

    def reached(*a, **k):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(subprocess, "run", started)
    monkeypatch.setattr(subprocess, "Popen", started)
    monkeypatch.setattr(socket, "create_connection", reached)
    monkeypatch.setattr(socket.socket, "connect", reached)


@pytest.fixture(autouse=True)
def a_machine_of_its_own(monkeypatch):
    """The tests say what machine the plugin is on; the one they happen to run on (a WSL distribution, where the
    plugin's page ends with its "Under WSL" table) is not read."""
    from liminal_libs.machines import linux as linux_mod

    if hasattr(linux_mod, "wsl"):
        monkeypatch.setattr(linux_mod, "wsl", lambda release=None, env=None: "")
