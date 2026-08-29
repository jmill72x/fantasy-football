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
