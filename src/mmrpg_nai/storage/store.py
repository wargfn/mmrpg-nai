"""JSON file-based persistence store for all MMRPG data."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from mmrpg_nai.models.core import (
    Adventure,
    Campaign,
    Character,
    Equipment,
    NarratorConfig,
    PowerSet,
    Session,
    SourceMaterial,
    User,
)

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class _Repo(Generic[T]):
    """Generic JSON-file repository for a Pydantic model."""

    def __init__(self, directory: Path, model_cls: type[T]) -> None:
        self._dir = _ensure(directory)
        self._cls = model_cls

    def _path(self, id_: str) -> Path:
        if (
            not id_
            or id_ in {".", ".."}
            or Path(id_).name != id_
            or "/" in id_
            or "\\" in id_
        ):
            raise ValueError(f"Invalid id: {id_!r}")
        return self._dir / f"{id_}.json"

    def save(self, obj: T) -> T:
        id_ = getattr(obj, "id", None)
        if id_ is None:
            raise ValueError(f"{obj!r} has no 'id' field")
        self._path(id_).write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        return obj

    def load(self, id_: str) -> T | None:
        try:
            p = self._path(id_)
        except ValueError:
            logger.warning("Rejected invalid id: %r", id_)
            return None
        if not p.exists():
            return None
        try:
            return self._cls.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping corrupt data file %s: %s", p, exc)
            return None

    def delete(self, id_: str) -> bool:
        try:
            p = self._path(id_)
        except ValueError:
            logger.warning("Rejected invalid id: %r", id_)
            return False
        if p.exists():
            p.unlink()
            return True
        return False

    def list_all(self) -> list[T]:
        items: list[T] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                items.append(self._cls.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Skipping corrupt data file %s: %s", p, exc)
        return items

    def load_by_prefix(self, prefix: str) -> T | None:
        """Load an item whose ID starts with *prefix*. Returns None if zero or multiple match."""
        matches = [p for p in self._dir.glob("*.json") if p.stem.startswith(prefix)]
        if len(matches) != 1:
            return None
        try:
            return self._cls.model_validate_json(matches[0].read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping corrupt data file %s: %s", matches[0], exc)
            return None

    def find(self, **filters: Any) -> list[T]:
        results = []
        for item in self.list_all():
            match = all(getattr(item, k, None) == v for k, v in filters.items())
            if match:
                results.append(item)
        return results


class Store:
    """Central data store backed by a directory of JSON files."""

    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir)
        self.base_dir: Path = base
        self.campaigns = _Repo(base / "campaigns", Campaign)
        self.sessions = _Repo(base / "sessions", Session)
        self.characters = _Repo(base / "characters", Character)
        self.equipment = _Repo(base / "equipment", Equipment)
        self.power_sets = _Repo(base / "power_sets", PowerSet)
        self.adventures = _Repo(base / "adventures", Adventure)
        self.source_materials = _Repo(base / "source_materials", SourceMaterial)
        self.users = _Repo(base / "users", User)
        self._base = base  # kept for backward-compat; prefer base_dir

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def load_config(self) -> NarratorConfig:
        p = self._base / "config.json"
        if p.exists():
            try:
                return NarratorConfig.model_validate_json(p.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Invalid config file %s; using defaults: %s", p, exc)
        return NarratorConfig()

    def save_config(self, cfg: NarratorConfig) -> NarratorConfig:
        p = self._base / "config.json"
        p.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        return cfg

    # ------------------------------------------------------------------
    # Convenience: session log append
    # ------------------------------------------------------------------

    def append_log(self, session: Session) -> Session:
        return self.sessions.save(session)

    def touch_users_for_session(self, user_ids: list[str]) -> None:
        if not user_ids:
            return
        now = datetime.now(timezone.utc)
        for uid in dict.fromkeys(user_ids):
            user = self.users.load(uid)
            if user is None:
                continue
            user.last_login_at = now
            user.session_timestamps.append(now)
            user.updated_at = now
            self.users.save(user)
