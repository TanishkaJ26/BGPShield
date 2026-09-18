"""One polite, retrying downloader, used by every ingest module.

Plan Section 16 asks for three things from anything that touches a public archive: a
descriptive User-Agent with a contact address, cached downloads, and respect for rate
limits. This module is where those live, so no ingest module has to reimplement them.

Downloads land in a temporary file next to the destination and are renamed into place only
once complete. A connection that drops halfway therefore leaves no truncated file behind
that a later run would mistake for a good cached copy.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests


class DownloadError(RuntimeError):
    """A file could not be fetched after every retry."""


def build_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    return session


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
        return dest

    last: Exception | str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with session.get(url, timeout=timeout, stream=True) as response:
                if response.status_code == 404:
                    return None
                if response.status_code >= 500:
                    last = f"HTTP {response.status_code}"
                    time.sleep(pause * attempt)
                    continue
                response.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(f"{dest.name}.part{os.getpid()}")
                written = 0
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        handle.write(chunk)
                        written += len(chunk)
                expected = response.headers.get("Content-Length")
                if expected is not None and written != int(expected):
                    tmp.unlink(missing_ok=True)
                    last = f"short read: {written} of {expected} bytes"
                    time.sleep(pause * attempt)
                    continue
                tmp.replace(dest)
                time.sleep(pause)
                return dest
        except requests.RequestException as exc:
            last = exc
            time.sleep(pause * attempt)

    raise DownloadError(f"giving up on {url} after {attempts} attempts: {last}")
