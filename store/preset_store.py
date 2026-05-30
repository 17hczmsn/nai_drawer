"""预设运行时缓存，持久化到 data 目录。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA_ROOT = Path("data") / "nai_drawer"
CHARACTER_DIR = DATA_ROOT / "characters"
VIBE_DIR = DATA_ROOT / "vibes"
CACHE_FILE = DATA_ROOT / "preset_cache.json"


class PresetStoreError(RuntimeError):
    """预设缓存读写失败。"""


@dataclass(frozen=True)
class CharacterCacheEntry:
    """已就绪的角色参考缓存。"""

    name: str
    stored_path: str
    source_path: str
    reference_type: str
    fidelity: float
    strength: float


@dataclass(frozen=True)
class VibeCacheEntry:
    """已就绪的 Vibe 缓存。"""

    name: str
    cache_id: str
    source_path: str
    reference_strength: float
    information_extracted: float


def _load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {"characters": {}, "vibes": {}}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PresetStoreError("预设缓存文件损坏，请检查 data/nai_drawer/preset_cache.json。") from exc
    if not isinstance(data, dict):
        return {"characters": {}, "vibes": {}}
    data.setdefault("characters", {})
    data.setdefault("vibes", {})
    return data


def _save_cache(data: dict[str, Any]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_stem(name: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in "._-" or "\u4e00" <= ch <= "\u9fff" else "_" for ch in name)
    return stem.strip("._") or "preset"


def copy_character_image(name: str, source_path: Path) -> Path:
    """把配置中的角色参考图复制到 data 目录。"""

    if not source_path.exists():
        raise PresetStoreError(f"角色参考图不存在：{source_path}")
    CHARACTER_DIR.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix or ".png"
    target = CHARACTER_DIR / f"{_safe_stem(name)}{suffix}"
    shutil.copy2(source_path, target)
    return target


def remember_character_cache(
    name: str,
    *,
    stored_path: Path,
    source_path: Path,
    reference_type: str,
    fidelity: float,
    strength: float,
) -> CharacterCacheEntry:
    """写入角色参考缓存。"""

    data = _load_cache()
    entry = {
        "stored_path": stored_path.as_posix(),
        "source_path": source_path.as_posix(),
        "reference_type": reference_type,
        "fidelity": fidelity,
        "strength": strength,
    }
    data["characters"][name] = entry
    _save_cache(data)
    return CharacterCacheEntry(name=name, **entry)


def get_character_cache(name: str) -> CharacterCacheEntry | None:
    """读取角色参考缓存。"""

    raw = _load_cache()["characters"].get(name)
    if not isinstance(raw, dict):
        return None
    stored_path = str(raw.get("stored_path", "") or "")
    if not stored_path:
        return None
    return CharacterCacheEntry(
        name=name,
        stored_path=stored_path,
        source_path=str(raw.get("source_path", "") or ""),
        reference_type=str(raw.get("reference_type", "character&style") or "character&style"),
        fidelity=float(raw.get("fidelity", 1.0)),
        strength=float(raw.get("strength", 1.0)),
    )


def remember_vibe_cache(
    name: str,
    *,
    cache_id: str,
    source_path: Path,
    reference_strength: float,
    information_extracted: float,
) -> VibeCacheEntry:
    """写入 Vibe cache_id 缓存。"""

    data = _load_cache()
    entry = {
        "cache_id": cache_id,
        "source_path": source_path.as_posix(),
        "reference_strength": reference_strength,
        "information_extracted": information_extracted,
    }
    data["vibes"][name] = entry
    _save_cache(data)
    return VibeCacheEntry(name=name, **entry)


def get_vibe_cache(name: str) -> VibeCacheEntry | None:
    """读取 Vibe 缓存。"""

    raw = _load_cache()["vibes"].get(name)
    if not isinstance(raw, dict):
        return None
    cache_id = str(raw.get("cache_id", "") or "").strip()
    if not cache_id:
        return None
    return VibeCacheEntry(
        name=name,
        cache_id=cache_id,
        source_path=str(raw.get("source_path", "") or ""),
        reference_strength=float(raw.get("reference_strength", 0.6)),
        information_extracted=float(raw.get("information_extracted", 0.7)),
    )
