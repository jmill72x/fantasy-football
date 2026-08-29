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
