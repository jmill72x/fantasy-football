import subprocess

import pytest

from sffl import notify


def test_dry_run_sends_nothing_and_reports_it():
    assert notify.send("topic", "t", "body", dry_run=True) is False


def test_an_empty_topic_raises_rather_than_posting_nowhere():
    with pytest.raises(ValueError):
        notify.send("", "t", "body")


def test_an_empty_body_raises():
    # A push with no body is worse than none: it looks like the job ran.
    with pytest.raises(ValueError):
        notify.send("topic", "t", "   ")


def test_a_missing_keychain_entry_names_the_command_that_creates_it():
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-does-not-exist-%s" % id(object()))
    assert "security add-generic-password" in str(exc.value)


def test_a_topic_with_a_space_is_refused():
    # NTFY_URL % topic interpolates straight into a URL path - a space
    # breaks the request rather than being silently swallowed.
    with pytest.raises(ValueError):
        notify.send("sffl notis", "t", "body")


def test_a_topic_with_a_slash_is_refused():
    # Worse than a space: a `/` would silently change the URL's TARGET
    # rather than merely malforming the request.
    with pytest.raises(ValueError):
        notify.send("sffl/notis", "t", "body")


def test_a_topic_of_only_letters_digits_underscore_and_hyphen_is_accepted():
    # Not a network assertion - dry_run=True never reaches urlopen. This
    # only proves the shape guard does not reject a legitimate topic.
    assert notify.send("sffl-alert-topic_9", "t", "body", dry_run=True) is False


def test_an_invalid_topic_error_never_echoes_the_offending_value():
    # The topic is a secret - anyone holding it can push to this user's
    # phone - and this exception can land in a launchd log file, which is a
    # place a secret must never reach. A distinctive sentinel makes an
    # accidental leak impossible to miss.
    sentinel = "SENTINEL-XYZ123 leak-check"
    with pytest.raises(ValueError) as exc:
        notify.send(sentinel, "t", "body")
    assert "SENTINEL-XYZ123" not in str(exc.value)


# --- I3: a locked keychain is not a missing entry --------------------------

class _FakeProc(object):
    def __init__(self, returncode, stderr):
        self.returncode = returncode
        self._stderr = stderr

    def communicate(self):
        return b"", self._stderr


def _stub_security(monkeypatch, returncode, stderr):
    monkeypatch.setattr(
        notify.subprocess, "Popen",
        lambda *a, **k: _FakeProc(returncode, stderr))


def test_a_missing_entry_suggests_the_runbook_command_with_the_U_flag(
        monkeypatch):
    # Without -U, `security` refuses to overwrite an existing item and
    # reports "already exists" - the reader then believes they set a new
    # topic while the OLD one is still in the Keychain. That mistake is
    # already recorded in this project's runbook as having happened.
    _stub_security(monkeypatch, 44,
                   b"security: SecKeychainSearchCopyNext: The specified item "
                   b"could not be found in the keychain.")
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-test")
    msg = str(exc.value)
    assert "no Keychain entry" in msg
    assert "security add-generic-password" in msg
    assert "-U" in msg


def test_a_locked_keychain_is_not_reported_as_a_missing_entry(monkeypatch):
    # The whole finding: this failure used to be diagnosed as "no Keychain
    # entry" with a command to CREATE one - the wrong fix, confidently
    # given, for an entry that is present and fine.
    _stub_security(monkeypatch, 51,
                   b"security: SecKeychainItemCopyContent: User interaction "
                   b"is not allowed.")
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-test")
    msg = str(exc.value)
    assert "no Keychain entry" not in msg
    assert "do not re-create it" in msg.lower()
    assert "unlock-keychain" in msg
    assert "User interaction is not allowed" in msg


def test_an_unrecognized_failure_reports_securitys_own_message(monkeypatch):
    # Discarding stderr is what made every failure look like the same one.
    _stub_security(monkeypatch, 1, b"security: something nobody predicted")
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-test")
    msg = str(exc.value)
    assert "something nobody predicted" in msg
    assert "NOT necessarily a missing entry" in msg
    assert "-U" in msg


def test_the_keychain_value_is_never_echoed_into_an_error(monkeypatch):
    # stdout is where `security` writes the topic. Even if a failing call
    # somehow produced one, no branch may put it in the message.
    sentinel = b"SENTINEL-TOPIC-9F2A"

    class _LeakyProc(object):
        returncode = 1

        def communicate(self):
            return sentinel, b"security: some failure"

    monkeypatch.setattr(notify.subprocess, "Popen",
                        lambda *a, **k: _LeakyProc())
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-test")
    assert "SENTINEL-TOPIC-9F2A" not in str(exc.value)


def test_a_missing_security_binary_is_not_a_missing_entry(monkeypatch):
    def boom(*a, **k):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(notify.subprocess, "Popen", boom)
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-test")
    assert "PATH problem" in str(exc.value)
    assert "no Keychain entry" not in str(exc.value)


# --------------------------------------------------------- tap-to-claim actions
#
# ntfy renders up to three tap buttons. Jeff's waiver targets get one each,
# deep-linking to CBS with the add already staged, so a claim can be made
# from the phone instead of from a terminal.

def test_a_league_url_becomes_a_view_action():
    from sffl.notify import _actions_header
    h = _actions_header([("ADD Foo", "https://stripesfantasyfootballleague."
                          "football.cbssports.com/stats/stats-main?default_add=RB:1")])
    assert h.startswith("view, ADD Foo, https://stripesfantasyfootballleague")


def test_an_off_league_url_is_dropped_entirely():
    # An action is a thing Jeff TAPS on his phone. An attacker-chosen URL
    # here is a phishing link delivered by his own tooling.
    from sffl.notify import _actions_header
    assert _actions_header([("Click", "https://evil.example.com/phish")]) is None


def test_a_comma_in_a_label_cannot_forge_a_second_action():
    """Labels come from CBS player names - remote data.

    The header format is `view, <label>, <url>`, semicolon-separated. A comma
    or semicolon inside a label would split it into extra FIELDS and forge a
    second button pointing wherever the attacker chose. The label may still
    CONTAIN attacker text - it is displayed, not followed - so what is
    asserted is structural: exactly one action, exactly three fields, and the
    URL field is the vetted league one.
    """
    from sffl.notify import _actions_header
    h = _actions_header([("A, view, X, https://evil.example.com",
                          "https://stripesfantasyfootballleague.football."
                          "cbssports.com/x")])
    assert h.count(";") == 0, "label split the header into two actions"
    fields = h.split(",")
    assert len(fields) == 3, "expected exactly view/label/url, got %r" % fields
    assert fields[0].strip() == "view"
    assert fields[2].strip().startswith(
        "https://stripesfantasyfootballleague.football.cbssports.com/")


def test_at_most_three_actions_are_sent():
    from sffl.notify import MAX_ACTIONS, _actions_header
    base = "https://stripesfantasyfootballleague.football.cbssports.com/x"
    h = _actions_header([("A%d" % i, base) for i in range(6)])
    assert h.count("view,") == MAX_ACTIONS


def test_no_actions_sets_no_header_value():
    from sffl.notify import _actions_header
    assert _actions_header(None) is None
    assert _actions_header([]) is None


# ------------------------------------------------------------- Discord feed
#
# Each alert also goes to #john-madden through the Jarvis toolkit's poster.
# Every test hands `send_discord` a fake runner and a fake poster path: the
# real poster reads a webhook URL from the Keychain and posts to Discord,
# and no test may do either.

_FAKE_POSTER = "/fake/jarvis/bin/discord-post"


class _FakeRunner(object):
    """Stands in for `subprocess.run`, recording each poster invocation."""

    def __init__(self, returncode=0, raises=None):
        self.returncode = returncode
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode)


def test_send_discord_dry_run_passes_flag():
    # The poster is TOLD it is a dry run rather than skipped, so a dry run
    # still proves it exists and accepts the body - it runs every input
    # check, but never reads the Keychain and never sends.
    run = _FakeRunner()
    assert notify.send_discord("SFFL Tuesday", "body", dry_run=True,
                               runner=run, poster=_FAKE_POSTER) is False
    (argv, kwargs), = run.calls
    assert argv == [_FAKE_POSTER, "--agent", "john-madden",
                    "--title", "SFFL Tuesday", "--dry-run"]
    # Neither stream is captured: the poster's one value-free line ("dry
    # run: N message(s)", or why it refused) belongs in the alert's log.
    for key in ("stdout", "stderr", "capture_output"):
        assert key not in kwargs, key
    # Only a real run omits the flag, and only a real run reports a post.
    assert notify.send_discord("SFFL Tuesday", "body", runner=run,
                               poster=_FAKE_POSTER) is True
    assert run.calls[1][0] == argv[:-1]


def test_send_discord_drops_non_league_actions():
    # The same rule as ntfy's buttons, through the same filter: a link in
    # the alert is a thing Jeff taps, so only the league's own https pages
    # are offered. The off-site link and the plain-http one both vanish.
    league = ("https://stripesfantasyfootballleague.football.cbssports.com"
              "/stats/stats-main?default_add=RB:1")
    run = _FakeRunner()
    notify.send_discord(
        "SFFL Tuesday", "WAIVER TARGETS • Foo",
        actions=[("Click", "https://evil.example.com/phish"),
                 ("ADD Foo", league),
                 ("Plain", "http://stripesfantasyfootballleague.football."
                           "cbssports.com/x")],
        runner=run, poster=_FAKE_POSTER)
    stdin = run.calls[0][1]["input"]
    # Bytes, encoded here as UTF-8: launchd sets no LANG, so a text-mode
    # pipe would encode with whatever the locale happened to be.
    assert isinstance(stdin, bytes)
    assert stdin.decode("utf-8") == (
        "WAIVER TARGETS • Foo\n\nADD Foo: " + league)


def test_send_discord_error_hides_body():
    # These messages land in the alert's launchd log. One reason the poster
    # refuses a body is that it looks like it holds a secret, so an error
    # quoting the body would print exactly what was refused. A distinctive
    # sentinel makes a leak impossible to miss.
    sentinel = "SENTINEL-BODY-7Q4 leak-check"
    with pytest.raises(RuntimeError) as exited:
        notify.send_discord("SFFL Tuesday", sentinel,
                            runner=_FakeRunner(returncode=2),
                            poster=_FAKE_POSTER)
    no_poster = _FakeRunner(raises=FileNotFoundError(
        2, "No such file or directory", _FAKE_POSTER))
    with pytest.raises(RuntimeError) as missing:
        notify.send_discord("SFFL Tuesday", sentinel, runner=no_poster,
                            poster=_FAKE_POSTER)
    assert str(exited.value) == "discord-post exited 2"
    assert str(missing.value) == (
        "jarvis discord-post not found at %s" % _FAKE_POSTER)
    for exc in (exited, missing):
        assert "SENTINEL-BODY-7Q4" not in str(exc.value)
