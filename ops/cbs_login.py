"""ONE-TIME, BY HAND: log in to CBS and leave the session in the automation's profile.

    ./.venv/bin/python ops/cbs_login.py

Opens a real browser window. Log in to CBS yourself - this script never sees,
asks for, or stores a password; it only holds the window open while you use it,
then closes it so the session is flushed to the profile directory. Every
scheduled run afterwards reuses that profile headlessly.

Re-run this whenever an alert reports SessionExpired.
"""

import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = "data/browser-profile"
LEAGUE = "https://stripesfantasyfootballleague.football.cbssports.com/"


def main():
    print("Opening a browser window. Log in to CBS, then press Return here.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LEAGUE)
        input("Press Return once you can see the league home page... ")
        text = page.inner_text("body")
        ctx.close()
    if "Sign In - CBSSports.com" in text:
        print("Still on the sign-in page - the session was NOT saved.")
        return 1
    print("Logged in. Session saved to %s" % PROFILE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
