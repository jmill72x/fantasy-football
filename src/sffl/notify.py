"""Push one message to ntfy. THE ONLY MODULE THAT POSTS ANYWHERE.

The topic is a secret - anyone holding it can push to Jeff's phone - so it
lives in the login Keychain and never in this public repo. `dry_run` is the
seam every test uses; nothing here is exercised against the network.

`PushNotification` IS DELIBERATELY NOT USED. It requires Remote Control to be
connected, and a launchd job at 4:45pm on a Friday cannot rely on that.

THE TOPIC IS INTERPOLATED STRAIGHT INTO A URL PATH (`NTFY_URL % topic`), so an
unvalidated topic is an injection surface even though the only person who can
ever WRITE the Keychain entry is Jeff himself: a stray space breaks the
request, and `/`, `?`, `#`, or `@` would silently change which URL gets hit.
`send()` validates the shape before it is ever used - see `_TOPIC_RE`. The
validation error NAMES THE PROBLEM ("contains a space") and NEVER THE VALUE:
this can land in a launchd log file, which is a place a secret must never
reach, so the offending topic is never echoed into the exception.
"""

import re
import subprocess
import urllib.request

NTFY_URL = "https://ntfy.sh/%s"
KEYCHAIN_ACCOUNT = "sffl-alert-ntfy-topic"

# What ntfy itself accepts in a topic name. Anything else either breaks the
# request (a space) or - worse - silently retargets it (a `/`, `?`, `#`, or
# `@` changes what the URL actually points at).
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def topic_from_keychain(account=KEYCHAIN_ACCOUNT):
    """The ntfy topic, read from the login Keychain."""
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-a", account, "-w"],
            stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        raise RuntimeError(
            "no Keychain entry for account %r. The ntfy topic is a secret and "
            "is never committed to this public repo. Create it once with:\n"
            "  security add-generic-password -a %s -s sffl -w <your-topic>"
            % (account, account))
    return out.decode("utf-8").strip()


def send(topic, title, body, dry_run=False):
    """POST `body` to the topic. Returns True if a request was actually made.

    Validated here, not in `topic_from_keychain`, so the guard protects every
    caller regardless of where the topic came from.
    """
    if not topic:
        raise ValueError("empty ntfy topic - refusing to post nowhere")
    if not _TOPIC_RE.match(topic):
        # NEVER interpolate `topic` into this message - see the module
        # docstring. Name what's wrong, not what the value is.
        problem = ("contains a space" if " " in topic
                   else "contains a character outside [A-Za-z0-9_-]")
        raise ValueError(
            "invalid ntfy topic - %s. A valid ntfy topic uses only letters, "
            "digits, underscore, and hyphen (e.g. 'sffl-alerts-9f2a')."
            % problem)
    if not body or not body.strip():
        raise ValueError(
            "empty alert body - refusing to send. A push with no body looks "
            "like the job ran correctly, which is worse than no push at all")
    if dry_run:
        return False
    req = urllib.request.Request(
        NTFY_URL % topic, data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "default"})
    urllib.request.urlopen(req, timeout=30).read()
    return True
