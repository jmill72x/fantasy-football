import pytest

from sffl import capture


def test_a_long_login_page_over_char_floor_identified_by_title_raises_session_expired():
    # The dangerous case: a login page that is long enough to pass the
    # character floor. Without title/URL checks, it would be saved and parsed
    # downstream as 'Jeff rosters nobody' — the exact failure we guard against.
    text = "Log In\n\n" + ("x" * 1500)  # Over the 1000-char floor
    title = capture.SESSION_EXPIRED_TITLE
    url = "https://example.invalid/teams/1"
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, url, title)
    assert "log in again" in str(exc.value).lower()


def test_a_page_identified_by_login_url_path_alone_raises_session_expired():
    # A login redirect where the title is unhelpful. The URL path is a reliable
    # signal that CBS sends only on expired sessions.
    text = "Some generic page content"
    url = "https://www.cbssports.com/login?param=value"
    title = "Some Page"  # Doesn't match SESSION_EXPIRED_TITLE
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, url, title)
    assert "log in again" in str(exc.value).lower()


def test_a_real_looking_page_with_normal_title_and_url_passes():
    # A plausible roster or projections page with a normal title and URL.
    text = "y" * 5000
    url = "https://stripesfantasyfootballleague.football.cbssports.com/teams/1"
    title = "My Team - Fantasy Football"
    assert capture.check_page_text(text, url, title) is None


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
