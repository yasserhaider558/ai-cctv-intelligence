"""Thread-safe JSON configuration manager.

The configuration lives in ``config/config.json`` next to the application. It is
created from :data:`config.defaults.DEFAULT_CONFIG` on first launch and merged
with the defaults on every load, so upgrading the application never leaves the
user with a missing key.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

from config.defaults import DEFAULT_CONFIG


class ConfigError(RuntimeError):
    """Raised when the configuration cannot be written to disk."""


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` and return ``base``."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _split(dotted: str) -> list[str]:
    parts = [p for p in str(dotted).split(".") if p]
    if not parts:
        raise KeyError("Empty configuration key")
    return parts


class ConfigManager:
    """Dot-path access to a nested configuration dictionary."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data: dict = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    # -- persistence -------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self._write()
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # Corrupt or unreadable file: keep defaults in memory. We do not
                # overwrite the file here so the user can inspect it.
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                return
            if not isinstance(raw, dict):
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                return
            self._data = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), raw)

    def save(self) -> None:
        with self._lock:
            self._write()

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            raise ConfigError(f"Could not save configuration to {self._path}: {exc}") from exc

    # -- access ------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in _split(dotted):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node) if isinstance(node, (dict, list)) else node

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        parts = _split(dotted)
        with self._lock:
            node = self._data
            for part in parts[:-1]:
                nxt = node.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    node[part] = nxt
                node = nxt
            node[parts[-1]] = value
            if save:
                self._write()

    def update(self, mapping: dict[str, Any], save: bool = True) -> None:
        """Apply several dot-path values in a single write."""
        with self._lock:
            for dotted, value in mapping.items():
                parts = _split(dotted)
                node = self._data
                for part in parts[:-1]:
                    nxt = node.get(part)
                    if not isinstance(nxt, dict):
                        nxt = {}
                        node[part] = nxt
                    node = nxt
                node[parts[-1]] = value
            if save:
                self._write()

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(DEFAULT_CONFIG)
            self._write()

    # -- convenience -------------------------------------------------------
    def section(self, name: str) -> dict:
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}
