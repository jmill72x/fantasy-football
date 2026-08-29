"""ONE-TIME, BY HAND: log in to CBS and leave the session in the automation's profile.

    ./.venv/bin/python ops/cbs_login.py

Opens a real browser window. Log in to CBS yourself - this script never sees,
asks for, or stores a password; it only holds the window open while you use it,
then closes it so the session is flushed to the profile directory. Every
scheduled run afterwards reuses that profile headlessly.

Re-run this whenever an alert reports SessionExpired.
"""

import os
import sys

from playwright.sync_api import sync_playwright

# Bootstrap sffl import path: sffl is not pip-installed, so this script must
# be able to import it from <repo>/src no matter where the script is invoked from.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_repo_src = os.path.join(_repo_root, "src")
sys.path.insert(0, _repo_src)

from sffl.capture import _is_session_expired

# Resolve profile directory to an absolute path, always within the repo root.
# This ensures the operator can log in from any working directory and the
# session lands in the same place the automation will look for it.
PROFILE_DIR = os.path.join(_repo_root, "data", "browser-profile")
LEAGUE = "https://stripesfantasyfootballleague.football.cbssports.com/"


def main():
    print("Opening a browser window. Log in to CBS, then press Return here.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LEAGUE)
            input("Press Return once you can see the league home page... ")
            # Check using the same signals as capture() does: title and final URL.
            # Never check body text; the title never appears there.
            if _is_session_expired(page.title(), page.url):
                print("Still on the sign-in page - the session was NOT saved.")
                return 1
            # Print the actual resolved path, not the string literal, so the
            # operator can verify the session landed in the right place.
            print("Logged in. Session saved to %s" % os.path.abspath(PROFILE_DIR))
            return 0
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
