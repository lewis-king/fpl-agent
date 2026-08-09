from __future__ import annotations

import json
from functools import lru_cache

from .paths import CONFIG


@lru_cache(maxsize=1)
def sources() -> dict:
    with (CONFIG / "sources.json").open(encoding="utf-8") as handle:
        return json.load(handle)

