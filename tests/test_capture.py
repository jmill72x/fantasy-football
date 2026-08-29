import pytest

from sffl import capture


def test_a_login_page_is_reported_as_an_expired_session():
    text = "Sign In - CBSSports.com\nLog In\nEmail\nPassword"
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, "https://example.invalid/teams/1")
    assert "log in again" in str(exc.value).lower()


def test_an_empty_page_is_refused_rather_than_saved():
    with pytest.raises(capture.CaptureError) as exc:
        capture.check_page_text("   \n  \n", "https://example.invalid/teams/1")
    assert "empty" in str(exc.value).lower()


def test_a_suspiciously_short_page_is_refused():
    # A real CBS page is thousands of characters. A 200-character body means
    # an interstitial, a rate limit, or an error page - never a roster.
    with pytest.raises(capture.CaptureError):
        capture.check_page_text("x" * 200, "https://example.invalid/teams/1")


def test_a_plausible_page_passes():
    assert capture.check_page_text("y" * 5000, "https://example.invalid/x") is None


def test_session_expiry_is_a_capture_error_so_one_handler_catches_both():
    assert issubclass(capture.SessionExpired, capture.CaptureError)
