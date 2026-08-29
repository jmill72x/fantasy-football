"""Push one message to ntfy. THE ONLY MODULE THAT POSTS ANYWHERE.

The topic is a secret - anyone holding it can push to Jeff's phone - so it
lives in the login Keychain and never in this public repo. `dry_run` is the
seam every test uses; nothing here is exercised against the network.

`PushNotification` IS DELIBERATELY NOT USED. It requires Remote Control to be
connected, and a launchd job at 4:45pm on a Friday cannot rely on that.
"""

import subprocess
import urllib.request

NTFY_URL = "https://ntfy.sh/%s"
KEYCHAIN_ACCOUNT = "sffl-alert-ntfy-topic"


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
    """POST `body` to the topic. Returns True if a request was actually made."""
    if not topic:
        raise ValueError("empty ntfy topic - refusing to post nowhere")
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
