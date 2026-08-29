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
reach, so the offending topic is never echoed into the exception. The same
rule holds for `topic_from_keychain`, which reports `security`'s own stderr
verbatim: that stream carries diagnostics, never the stored value, which
`security` writes only to stdout and only on success.
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


# The exact command the runbook's first-time setup section gives, `-U` and
# all. Kept as one string so the two can be diffed by eye: a suggestion that
# drifts from the runbook sends the reader in a direction the runbook then
# contradicts.
_CREATE_CMD = ("security add-generic-password -a %s -s sffl "
               "-w <your-topic> -U")


def topic_from_keychain(account=KEYCHAIN_ACCOUNT):
    """The ntfy topic, read from the login Keychain.

    WHY `security`'s OWN MESSAGE IS CAPTURED AND REPORTED. This used to
    discard stderr (`stderr=subprocess.DEVNULL`) and report every failure as
    "no Keychain entry", suggesting a command to CREATE one. A LOCKED
    keychain and an SSH session with no window server both fail here too,
    and for both of those the suggested fix is wrong twice over: creating an
    entry is not what is needed, and the suggested command omitted `-U`,
    which is the exact mistake this project's runbook already records
    happening once - without it `security` refuses to overwrite an existing
    item and reports "the specified item already exists", leaving the OLD
    topic in place while the reader believes they just set a new one. A
    misdiagnosis with a confident fix attached is worse than a raw error.

    THE TOPIC CANNOT LEAK THROUGH THIS. `security` writes the value to
    STDOUT and only on success; stderr carries diagnostics only, and every
    branch below either raises before stdout is read or returns it to the
    caller. The value is never interpolated into any message here.
    """
    try:
        proc = subprocess.Popen(
            ["security", "find-generic-password", "-a", account, "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
    except OSError as exc:
        raise RuntimeError(
            "could not run `security` to read the Keychain: %s. It ships "
            "with macOS at /usr/bin/security; this is a PATH problem, not a "
            "missing entry." % exc)

    if proc.returncode == 0:
        return out.decode("utf-8").strip()

    detail = err.decode("utf-8", "replace").strip() or "no error output"
    lowered = detail.lower()

    if "could not be found" in lowered or "item cannot be found" in lowered:
        raise RuntimeError(
            "no Keychain entry for account %r. The ntfy topic is a secret "
            "and is never committed to this public repo. Create it once, at "
            "the machine (not over SSH), with:\n  %s\n(`security` said: %s)"
            % (account, _CREATE_CMD % account, detail))

    if "interaction is not allowed" in lowered or "user interaction" in lowered:
        raise RuntimeError(
            "the Keychain refused to release the entry for account %r "
            "because it could not prompt: the login keychain is locked, or "
            "this ran over SSH with no window server. THE ENTRY IS PROBABLY "
            "FINE - do not re-create it. Unlock it with `security "
            "unlock-keychain ~/Library/Keychains/login.keychain-db`, or run "
            "at the machine.\n(`security` said: %s)" % (account, detail))

    raise RuntimeError(
        "reading the Keychain entry for account %r failed with exit %d. "
        "This is NOT necessarily a missing entry - check the message before "
        "creating one, and note that re-creating it needs the `-U` flag "
        "(`%s`) or `security` will refuse and leave the old value in "
        "place.\n(`security` said: %s)"
        % (account, proc.returncode, _CREATE_CMD % account, detail))


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
