"""
Cache Module — StackHeal AI
MD5-keyed in-memory + disk cache with TTL.

Usage:
    from cache import get_cache, set_cache, clear_cache, cache_stats
"""

import hashlib
import json
import os
import time
import threading
from typing import Any, Optional

CACHE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".stackheal_cache")
TTL_SECONDS = 60 * 60 * 6      # 6 hours
MAX_MEM     = 512               # max in-memory entries

os.makedirs(CACHE_DIR, exist_ok=True)

_mem: dict  = {}                # key → (value, expiry_ts)
_lock       = threading.Lock()


def make_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _disk_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def get_cache(key: str) -> Optional[Any]:
    now = time.time()
    with _lock:
        entry = _mem.get(key)
        if entry:
            value, expiry = entry
            if now < expiry:
                return value
            del _mem[key]

    path = _disk_path(key)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if now < obj["expiry"]:
                _mem_set(key, obj["value"], obj["expiry"])
                return obj["value"]
            else:
                os.remove(path)
        except Exception:
            pass
    return None


def set_cache(key: str, value: Any, ttl: int = TTL_SECONDS) -> None:
    expiry = time.time() + ttl
    _mem_set(key, value, expiry)
    try:
        with open(_disk_path(key), "w", encoding="utf-8") as f:
            json.dump({"value": value, "expiry": expiry}, f)
    except Exception:
        pass


def clear_cache(key: Optional[str] = None) -> int:
    count = 0
    if key:
        with _lock:
            if key in _mem:
                del _mem[key]
                count += 1
        path = _disk_path(key)
        if os.path.exists(path):
            os.remove(path)
            count += 1
        return count

    with _lock:
        count += len(_mem)
        _mem.clear()

    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            try:
                os.remove(os.path.join(CACHE_DIR, fname))
                count += 1
            except Exception:
                pass
    return count


def cache_stats() -> dict:
    disk_files = [f for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
    return {
        "memory_entries": len(_mem),
        "disk_entries":   len(disk_files),
        "cache_dir":      CACHE_DIR,
        "ttl_hours":      TTL_SECONDS / 3600,
    }


def _mem_set(key: str, value: Any, expiry: float) -> None:
    with _lock:
        if len(_mem) >= MAX_MEM:
            oldest = min(_mem, key=lambda k: _mem[k][1])
            del _mem[oldest]
        _mem[key] = (value, expiry)
