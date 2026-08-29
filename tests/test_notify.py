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
