"""Test-wide guards: no test may reach the network, or depend on today's date.

Every test runs with outbound internet connections refused, so a test that
forgets to stub a fetch (nflverse, Sleeper, ESPN, ntfy, Discord, CBS) fails
loudly instead of quietly calling a real service. Local sockets (AF_UNIX) and
child processes such as `git` are not affected.

Every test also runs on a fixed "today" for `sffl.season` (the stale-season
check): 21 October of the default league profile's own season. Without it the
alert, week and trade tests would go red on 1 March of the next year, the day
the default profile goes stale, and stay red until the new profile lands in
August - the suite must not break by the calendar. A test about dates stubs
`sffl.season.today` itself.
"""

import datetime
import functools
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


@functools.lru_cache(maxsize=1)
def _default_profile_season():
    from sffl.cli import DEFAULT_LEAGUE
    from sffl.league import load_league

    return load_league(DEFAULT_LEAGUE).season


@pytest.fixture(autouse=True)
def _in_season_today(monkeypatch):
    day = datetime.date(_default_profile_season(), 10, 21)
    monkeypatch.setattr("sffl.season.today", lambda: day)
