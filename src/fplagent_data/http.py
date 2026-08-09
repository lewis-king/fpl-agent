from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .paths import MANIFESTS, ensure_layout

USER_AGENT = "fplagent-data/0.1 (public-data research; https://fplagent.com)"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _record(path: Path, url: str, status: str) -> None:
    ensure_layout()
    item = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "path": str(path),
        "url": url,
        "status": status,
        "bytes": path.stat().st_size if path.exists() else None,
        "sha256": sha256_file(path) if path.exists() else None,
    }
    with (MANIFESTS / "raw_files.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def download(
    url: str,
    destination: Path,
    *,
    optional: bool = False,
    force: bool = False,
    retries: int = 5,
    timeout: int = 120,
    throttle_seconds: float = 0.0,
) -> Path | None:
    """Download a public artifact atomically, cache it and record provenance."""
    ensure_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0 and not force:
        return destination

    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(retries):
        if throttle_seconds:
            time.sleep(throttle_seconds)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            os.replace(partial, destination)
            _record(destination, url, "downloaded")
            return destination
        except urllib.error.HTTPError as exc:
            partial.unlink(missing_ok=True)
            if exc.code in {404, 410} and optional:
                _record(destination, url, f"unavailable_http_{exc.code}")
                return None
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            retry_after = float(exc.headers.get("Retry-After", 0) or 0)
            time.sleep(max(retry_after, (2**attempt) + random.random()))
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ):
            partial.unlink(missing_ok=True)
            if attempt == retries - 1:
                raise
            time.sleep((2**attempt) + random.random())
    return None


def download_json(url: str, destination: Path, **kwargs) -> dict | None:
    path = download(url, destination, **kwargs)
    if path is None:
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
