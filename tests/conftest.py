"""Test-wide guard: no test may reach the network.

Every test runs with outbound internet connections refused, so a test that
forgets to stub a fetch (nflverse, Sleeper, ESPN, ntfy, Discord, CBS) fails
loudly instead of quietly calling a real service. Local sockets (AF_UNIX) and
child processes such as `git` are not affected.
"""

import socket

import pytest


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to open an internet connection."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def refuse(address):
        raise NetworkBlocked("tests may not open network connections "
                             "(tried %r); stub the fetch" % (address,))

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            refuse(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            refuse(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        refuse(address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
