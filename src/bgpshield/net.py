"""One polite, retrying downloader, used by every ingest module.

Plan Section 16 asks for three things from anything that touches a public archive: a
descriptive User-Agent with a contact address, cached downloads, and respect for rate
limits. This module is where those live, so no ingest module has to reimplement them.

Downloads land in a temporary file next to the destination and are renamed into place only
once complete. A connection that drops halfway therefore leaves no truncated file behind
that a later run would mistake for a good cached copy.

Retries back off exponentially, and a ``429 Too Many Requests`` or ``503`` that carries a
``Retry-After`` header is honoured (capped, so a misconfigured server cannot park a job for
an hour). Every attempt is logged at DEBUG; ``bgpshield --verbose`` turns that on.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

#: The longest a ``Retry-After`` header is allowed to hold a download.
MAX_RETRY_AFTER_SECONDS = 120.0

#: Statuses worth retrying: rate limiting and anything on the server's side.
_RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})


class DownloadError(RuntimeError):
    """A file could not be fetched after every retry."""


def build_session(user_agent: str) -> requests.Session:
    """A session that identifies this project on every request (plan Section 16)."""
    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    return session


def _retry_delay(retry_after: str | None, attempt: int, pause: float) -> float:
    """How long to wait before the next attempt.

    ``Retry-After`` wins when the server sent one and it parses as seconds; otherwise the
    delay doubles with each attempt starting from ``pause``.
    """
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    return pause * 2.0 ** (attempt - 1)


def download(
    session: requests.Session,
    url: str,
    dest: Path,
    *,
    force: bool = False,
    attempts: int = 4,
    pause: float = 0.5,
    timeout: float = 300.0,
) -> Path | None:
    """Fetch ``url`` into ``dest``, reusing a cached copy unless ``force``.

    Returns the path, or ``None`` if the server said 404, which for these archives means
    "no file was published for that day" rather than an error. Raises ``DownloadError``
    when every attempt fails, so a caller can report the failure instead of silently
    carrying on with missing data (Section 0, rule 3).
    """
    if dest.exists() and dest.stat().st_size > 0 and not force:
        log.debug("cached %s", dest)
        return dest

    last: Exception | str | None = None
    for attempt in range(1, attempts + 1):
        log.debug("GET %s (attempt %d of %d)", url, attempt, attempts)
        try:
            with session.get(url, timeout=timeout, stream=True) as response:
                if response.status_code == 404:
                    log.debug("404 %s", url)
                    return None
                if response.status_code in _RETRYABLE:
                    last = f"HTTP {response.status_code}"
                    delay = _retry_delay(response.headers.get("Retry-After"), attempt, pause)
                    log.debug("%s for %s; retrying in %.1fs", last, url, delay)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(f"{dest.name}.part{os.getpid()}")
                written = 0
                try:
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            handle.write(chunk)
                            written += len(chunk)
                except BaseException:
                    tmp.unlink(missing_ok=True)
                    raise
                # Content-Length counts the bytes on the wire. When the server applies a
                # transfer encoding, `iter_content` hands back the decoded body, which is
                # legitimately longer, so the comparison would reject a perfectly good file
                # on every attempt and turn a working source into a hard failure.
                encoded = response.headers.get("Content-Encoding")
                expected = (
                    None if encoded else _content_length(response.headers.get("Content-Length"))
                )
                if expected is not None and written != expected:
                    tmp.unlink(missing_ok=True)
                    last = f"short read: {written} of {expected} bytes"
                    delay = _retry_delay(None, attempt, pause)
                    log.debug("%s for %s; retrying in %.1fs", last, url, delay)
                    time.sleep(delay)
                    continue
                tmp.replace(dest)
                log.debug("wrote %s (%d bytes)", dest, written)
                time.sleep(pause)
                return dest
        except requests.RequestException as exc:
            last = exc
            delay = _retry_delay(None, attempt, pause)
            log.debug("%s for %s; retrying in %.1fs", exc, url, delay)
            time.sleep(delay)

    raise DownloadError(f"giving up on {url} after {attempts} attempts: {last}")


def _content_length(value: str | None) -> int | None:
    """The declared body length, or ``None`` when absent or unparseable."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
