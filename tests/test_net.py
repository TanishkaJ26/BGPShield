"""Unit tests for the shared downloader (plan Sections 12 and 16).

No network here. A fake session replays canned responses, including the truncated
transfer that actually happened while fetching a registry file on 2026-09-18.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import pytest
import requests

from bgpshield import net


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"payload",
        *,
        content_length: int | None = None,
        truncate_to: int | None = None,
    ) -> None:
        self.status_code = status
        self._body = body
        declared = len(body) if content_length is None else content_length
        self.headers = {"Content-Length": str(declared)}
        self._truncate_to = truncate_to

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> Any:
        body = self._body if self._truncate_to is None else self._body[: self._truncate_to]
        yield body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns each queued response in turn; raises if asked for more than were queued."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self._queue = list(responses)
        self.calls = 0

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        if not self._queue:
            raise AssertionError(f"unexpected extra request for {url}")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_download_writes_the_file(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(body=b"hello"))
    dest = tmp_path / "sub" / "file.bin"
    result = net.download(session, "https://example.invalid/f", dest, pause=0)  # type: ignore[arg-type]
    assert result == dest
    assert dest.read_bytes() == b"hello"


def test_download_reuses_the_cache(tmp_path: Path) -> None:
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"cached")
    session = FakeSession()  # any request at all would fail the test
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert session.calls == 0


def test_force_redownloads(tmp_path: Path) -> None:
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"stale")
    session = FakeSession(FakeResponse(body=b"fresh"))
    net.download(session, "https://example.invalid/f", dest, force=True, pause=0)  # type: ignore[arg-type]
    assert dest.read_bytes() == b"fresh"


def test_404_means_nothing_published_that_day(tmp_path: Path) -> None:
    """The archives return 404 for days they never published, which is not an error."""
    session = FakeSession(FakeResponse(status=404))
    assert net.download(session, "https://example.invalid/f", tmp_path / "f", pause=0) is None  # type: ignore[arg-type]


def test_retries_a_server_error_then_succeeds(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(status=503), FakeResponse(body=b"ok"))
    dest = tmp_path / "file.bin"
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert session.calls == 2
    assert dest.read_bytes() == b"ok"


def test_retries_a_dropped_connection(tmp_path: Path) -> None:
    """This is the failure seen on a real registry download: the transfer broke mid-file."""
    session = FakeSession(
        requests.ConnectionError("Connection broken: IncompleteRead"),
        FakeResponse(body=b"ok"),
    )
    dest = tmp_path / "file.bin"
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert dest.read_bytes() == b"ok"


def test_a_truncated_body_is_never_cached(tmp_path: Path) -> None:
    """A short read must not leave a partial file that a later run trusts as complete."""
    session = FakeSession(
        FakeResponse(body=b"0123456789", truncate_to=4),
        FakeResponse(body=b"0123456789"),
    )
    dest = tmp_path / "file.bin"
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert dest.read_bytes() == b"0123456789"
    assert list(tmp_path.glob("*.part*")) == []


def test_gives_up_loudly_rather_than_returning_bad_data(tmp_path: Path) -> None:
    session = FakeSession(*[FakeResponse(status=500) for _ in range(4)])
    with pytest.raises(net.DownloadError, match="giving up"):
        net.download(session, "https://example.invalid/f", tmp_path / "f", attempts=4, pause=0)  # type: ignore[arg-type]
    assert not (tmp_path / "f").exists()


def test_rate_limiting_waits_as_long_as_the_server_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 with Retry-After is the archive asking for patience, and it gets it."""
    slept: list[float] = []
    monkeypatch.setattr(net.time, "sleep", lambda seconds: slept.append(seconds))
    limited = FakeResponse(status=429)
    limited.headers["Retry-After"] = "3"
    session = FakeSession(limited, FakeResponse(body=b"ok"))
    dest = tmp_path / "file.bin"
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert slept[0] == 3.0
    assert dest.read_bytes() == b"ok"


def test_retry_after_is_capped_so_a_bad_header_cannot_park_a_job() -> None:
    assert net._retry_delay("99999", 1, 0.5) == net.MAX_RETRY_AFTER_SECONDS


def test_backoff_doubles_between_attempts() -> None:
    assert [net._retry_delay(None, attempt, 0.5) for attempt in (1, 2, 3)] == [0.5, 1.0, 2.0]


def test_an_unparseable_retry_after_falls_back_to_backoff() -> None:
    assert net._retry_delay("soon", 2, 0.5) == 1.0


def test_a_garbage_content_length_does_not_reject_a_good_body(tmp_path: Path) -> None:
    response = FakeResponse(body=b"payload")
    response.headers["Content-Length"] = "banana"
    session = FakeSession(response)
    dest = tmp_path / "file.bin"
    assert net.download(session, "https://example.invalid/f", dest, pause=0) == dest  # type: ignore[arg-type]
    assert dest.read_bytes() == b"payload"
