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
