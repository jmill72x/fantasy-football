"""Push one alert to ntfy and to Discord. THE ONLY MODULE THAT POSTS ANYWHERE.

The topic is a secret - anyone holding it can push to Jeff's phone - so it
lives in the login Keychain and never in this public repo. `dry_run` is the
seam every ntfy test uses; nothing here is exercised against the network.

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

DISCORD IS REACHED ONLY THROUGH THE JARVIS TOOLKIT'S POSTER (`DISCORD_POSTER`),
which reads #john-madden's webhook URL from the Keychain itself. That URL is
a secret too, and it never passes through this repo: `send_discord` hands the
poster a title and a body, never a URL. The poster's own output names neither
the URL nor the body, so it is left to reach the log, and the errors
`send_discord` raises carry only an exit status or the poster's path. Its
tests inject `runner` rather than lean on `dry_run`, because a Discord dry
run still runs the poster.
"""

import os
import re
import subprocess
import sys
import urllib.request

LEAGUE_URL_PREFIX = (
    "https://stripesfantasyfootballleague.football.cbssports.com/")

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


# ntfy renders at most three tap actions per notification, and silently
# drops the rest - so callers must hand over the three that matter, already
# ranked, rather than everything they have.
MAX_ACTIONS = 3


def _allowed_actions(actions):
    """[(clean_label, url)] for the actions that may be offered at all.

    ntfy's buttons and Discord's link lines both come from here, so the two
    channels can never disagree about what is safe to tap. URLs are accepted
    only when they point at the league host over https - an action is a
    thing Jeff taps on his phone, so an attacker-chosen URL here is a
    phishing link delivered by his own tooling. Labels are sanitised rather
    than trusted, because they are built from CBS player names, which are
    remote data: a comma or semicolon would split ntfy's header (see
    `_actions_header`), and a line break would forge an extra line in the
    Discord post. A label with nothing left after that is dropped, action
    and all.
    """
    out = []
    for label, url in (actions or [])[:MAX_ACTIONS]:
        if not url.startswith(LEAGUE_URL_PREFIX):
            continue
        clean = "".join(ch for ch in str(label) if ch not in ",;\r\n").strip()
        if not clean:
            continue
        out.append((clean, url))
    return out


def _actions_header(actions):
    """ntfy `Actions` header value for [(label, url)], or None.

    Format is `view, <label>, <url>` per action, semicolon-separated. A LABEL
    CONTAINING A COMMA OR SEMICOLON WOULD SPLIT THE HEADER and forge extra
    actions, which is one of the reasons every action is vetted by
    `_allowed_actions` before it gets here.
    """
    return "; ".join("view, %s, %s" % action
                     for action in _allowed_actions(actions)) or None


def send(topic, title, body, dry_run=False, actions=None):
    """POST `body` to the topic. Returns True if a request was actually made.

    Validated here, not in `topic_from_keychain`, so the guard protects every
    caller regardless of where the topic came from.

    `actions` is [(label, url)] rendered as tappable buttons on the phone -
    used to deep-link a waiver claim straight into CBS with the add already
    staged, so Jeff can act on the digest from the notification instead of
    getting to a terminal. Silently ignored if empty; see `_actions_header`
    for why the URLs are restricted to the league host.
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
    headers = {"Title": title, "Priority": "default"}
    act = _actions_header(actions)
    if act:
        headers["Actions"] = act
    req = urllib.request.Request(
        NTFY_URL % topic, data=body.encode("utf-8"), headers=headers)
    urllib.request.urlopen(req, timeout=30).read()
    return True


# The Jarvis toolkit's poster: `discord-post --agent <slug> [--title T]
# [--dry-run]`, body on stdin. It exits 0 when it posted (or a dry run
# passed), 2 on a refusal or a configuration problem - an unknown feed, an
# empty or secret-shaped body, no webhook in the Keychain - and 3 when
# Discord or the network failed. It bounds its own network and Keychain
# calls, which is why nothing here adds a timeout of its own. "Not found"
# can also mean the poster IS there but its shebang interpreter is not:
# exec reports ENOENT for both, so that message names the poster's path
# either way - check its `#!` line before assuming the file is missing.
DISCORD_POSTER = os.path.expanduser("~/Projects/jarvis/bin/discord-post")


def send_discord(title, body, dry_run=False, actions=None,
                 runner=subprocess.run, poster=DISCORD_POSTER):
    """Post `body` to #john-madden. Returns True if it was actually posted.

    A dry run still RUNS the poster, with `--dry-run`, rather than skipping
    it: the poster then makes the same input checks a real post does - the
    feed, the body, the secret scan - but never reads the Keychain or sends
    anything, so a rehearsal proves the body would be accepted. It returns
    False.

    `actions` are the [(label, url)] ntfy gets as buttons. Discord has no
    buttons, so each becomes a `<label>: <url>` line after a blank line,
    which Discord renders as a tappable link. They go through the same
    `_allowed_actions` vetting, so both channels offer the same links.

    THE BODY GOES ON STDIN AS UTF-8 BYTES, not text: launchd sets no LANG,
    so a text-mode pipe would encode with whatever the locale happened to
    be. NEITHER OUTPUT STREAM IS CAPTURED: the poster prints one line - how
    many messages it posted, or why it would not - naming neither the
    webhook URL nor the body, and that line belongs in this run's log.

    Raises ValueError for a blank body, before the poster is run. Raises
    RuntimeError when the poster is missing or exits non-zero, carrying
    only its path or its exit status - NEVER THE BODY. One reason the
    poster refuses a body is that it looks like it holds a secret, and an
    error quoting the body would print exactly that text wherever the error
    is shown. Any other OSError from starting the poster propagates.
    """
    # Refused HERE, not left to the poster: the poster does refuse an empty
    # body, but the claim links appended below make its stdin non-empty, so
    # a blank digest would post its links alone.
    if not body or not body.strip():
        raise ValueError(
            "empty alert body - refusing to post to Discord. A post with no "
            "body looks like the job ran correctly, which is worse than no "
            "post at all")
    argv = [poster, "--agent", "john-madden", "--title", title]
    if dry_run:
        argv.append("--dry-run")
    text = body
    links = _allowed_actions(actions)
    if links:
        text += "\n\n" + "\n".join("%s: %s" % link for link in links)
    # Flushed first: the poster writes straight to this process's stdout,
    # which under launchd is a log file Python buffers - unflushed, the
    # poster's line would land in the log ahead of the digest it reports on.
    sys.stdout.flush()
    try:
        proc = runner(argv, input=text.encode("utf-8"))
    except FileNotFoundError:
        raise RuntimeError(
            "jarvis discord-post not found at %s" % poster) from None
    if proc.returncode != 0:
        raise RuntimeError("discord-post exited %d" % proc.returncode)
    return not dry_run
