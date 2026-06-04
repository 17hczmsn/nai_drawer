"""本地 Danbooru Tag 向量检索实现。

基于预计算的 embedding 向量进行余弦相似度搜索，
需要预构建的数据文件：
- data/nai_drawer/danbooru_tags.json - Tag 列表 + 中文描述
- data/nai_drawer/tag_embeddings.npy - 预计算的 embedding 矩阵

示例数据使用本模块内置的字符 n-gram 哈希向量生成，
无需外部 embedding API 即可作为本地检索示例运行。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.app.plugin_system.api.log_api import get_logger

logger = get_logger("nai_drawer.tag_retriever")

# 默认数据目录
_DEFAULT_DATA_DIR = Path("data/nai_drawer")
_HASH_EMBEDDING_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9_()]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_CACHE_WRITE_LOCK = asyncio.Lock()


def _tag_key(tag: str) -> str:
    """生成用于本地缓存去重的 tag key。"""
    return tag.strip().lower()


def _normalize_text(text: str) -> str:
    """规范化检索文本，统一大小写与常见分隔符。"""
    return text.lower().replace("_", " ").replace("-", " ")


def _iter_features(text: str) -> list[str]:
    """从文本中提取字符 n-gram 与 token 特征。"""
    normalized = _normalize_text(text)
    compact = re.sub(r"\s+", "", normalized)
    features: list[str] = []

    for token in _TOKEN_RE.findall(normalized):
        features.append(token)
        if re.search(r"[\u4e00-\u9fff]", token):
            features.extend(token[i:i + 2] for i in range(max(len(token) - 1, 0)))
        elif len(token) >= 3:
            features.extend(token[i:i + 3] for i in range(len(token) - 2))

    if len(compact) >= 2:
        features.extend(compact[i:i + 2] for i in range(len(compact) - 1))
    return [feature for feature in features if feature]


def build_hash_embedding(text: str, dim: int = _HASH_EMBEDDING_DIM) -> Any:
    """使用字符 n-gram 哈希构建本地示例 embedding。"""
    import numpy as np

    vector = np.zeros(dim, dtype=np.float32)
    for feature in _iter_features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = float(np.linalg.norm(vector))
    if norm > 0.0:
        vector /= norm
    return vector


def build_tag_embedding_text(item: dict[str, Any]) -> str:
    """构建 tag 条目的本地 embedding 文本。"""
    aliases = item.get("aliases", [])
    alias_text = " ".join(str(alias) for alias in aliases) if isinstance(aliases, list) else str(aliases or "")
    return " ".join(
        part
        for part in [
            str(item.get("tag", "")),
            str(item.get("cn_name", "")),
            str(item.get("category", "")),
            alias_text,
        ]
        if part
    )


def _split_cn_names(text: str) -> list[str]:
    """拆分中文名字段，避免把作品名当作所有角色的精确别名。"""
    return [part.strip() for part in re.split(r"[,，/|]", text) if part.strip()]


def _term_key(text: str) -> str:
    """生成用于别名比较的紧凑 key。"""
    return re.sub(r"\s+", "", _normalize_text(text))


def _category_key(category: str) -> str:
    """规范化 Danbooru 分类名称。"""
    return category.strip().lower()


def _copyright_match_terms(tags: list[dict[str, Any]]) -> set[str]:
    """从现有 Copyright 条目中提取作品名匹配词。"""
    terms: set[str] = set()
    for item in tags:
        if _category_key(str(item.get("category", ""))) != "copyright":
            continue
        tag = str(item.get("tag", "")).strip()
        if tag:
            terms.add(_term_key(tag))
            terms.add(_term_key(tag.replace("_", " ")))
        for name in _split_cn_names(str(item.get("cn_name", ""))):
            terms.add(_term_key(name))
        aliases = item.get("aliases", [])
        if isinstance(aliases, list):
            terms.update(_term_key(str(alias)) for alias in aliases if str(alias).strip())
        elif aliases:
            terms.add(_term_key(str(aliases)))
    return {term for term in terms if term}


def _tag_base_alias(tag: str) -> str:
    """从带作品限定的角色 tag 中提取基础英文别名。"""
    base = re.sub(r"_?\([^)]*\)$", "", tag.strip())
    return base.replace("_", " ").strip()


def _clean_character_names(item: dict[str, Any], copyright_terms: set[str]) -> list[str]:
    """清理 Character 的名称字段，避免混入作品名。"""
    names = _split_cn_names(str(item.get("cn_name", "")))
    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        names.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    elif aliases:
        names.append(str(aliases).strip())

    tag_base = _tag_base_alias(str(item.get("tag", "")))
    if tag_base:
        names.append(tag_base)

    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = _term_key(name)
        if not key or key in copyright_terms or key in seen:
            continue
        cleaned.append(name)
        seen.add(key)
    return cleaned


def _match_terms(item: dict[str, Any]) -> list[str]:
    """构建用于精确命中的 tag 名与别名。"""
    terms: list[str] = []
    tag = str(item.get("tag", ""))
    if tag:
        terms.extend([tag, tag.replace("_", " ")])

    aliases = item.get("aliases", [])
    if isinstance(aliases, list):
        terms.extend(str(alias) for alias in aliases)
    elif aliases:
        terms.append(str(aliases))

    cn_names = _split_cn_names(str(item.get("cn_name", "")))
    if cn_names:
        terms.append(cn_names[0])

    normalized_terms = {_normalize_text(term).strip() for term in terms if str(term).strip()}
    return sorted(normalized_terms, key=len, reverse=True)


def _exact_match_score(query: str, item: dict[str, Any]) -> float:
    """计算 query 对 tag 条目的精确别名命中分。"""
    normalized_query = _normalize_text(query)
    compact_query = re.sub(r"\s+", "", normalized_query)
    for term in _match_terms(item):
        compact_term = re.sub(r"\s+", "", term)
        if len(compact_term) >= 2 and compact_term in compact_query:
            return 1.0
    return 0.0


class TagRetriever:
    """本地 Tag 向量检索器。

    通过预计算的 embedding 矩阵进行余弦相似度搜索，
    返回与用户查询最相关的 Danbooru 标签候选。

    使用流程：
    1. 预构建 danbooru_tags.json 和 tag_embeddings.npy
    2. 调用 retrieve() 进行检索
    """

    def __init__(
        self,
        data_dir: str | Path = _DEFAULT_DATA_DIR,
        top_k: int = 50,
        min_score: float = 0.05,
    ) -> None:
        """初始化本地检索器。

        Args:
            data_dir: 数据目录路径，包含 danbooru_tags.json 和 tag_embeddings.npy
            top_k: 返回的候选数量
            min_score: 最小相似度阈值，低于此分数的候选被过滤
        """
        self.data_dir = Path(data_dir)
        self.top_k = top_k
        self.min_score = min_score

        self._tags: list[dict[str, str]] | None = None
        self._embeddings: Any | None = None  # numpy.ndarray，延迟导入
        self._loaded: bool = False

    async def retrieve(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """从本地向量库检索与查询最相关的标签。

        Args:
            query: 用户自然语言描述

        Returns:
            {'search': [{'tag': ..., 'cn_name': ..., 'category': ..., 'score': ...}, ...], 'related': []}
            失败时返回空结构
        """
        empty_result: dict[str, list[dict[str, Any]]] = {"search": [], "related": []}

        if not query or not query.strip():
            return empty_result

        try:
            await self._ensure_loaded()
        except FileNotFoundError as e:
            logger.warning(f"本地数据文件不存在，跳过本地检索: {e}")
            return empty_result
        except Exception as e:
            logger.error(f"加载本地数据失败: {e}")
            return empty_result

        if self._tags is None or self._embeddings is None:
            logger.warning("本地数据未加载，跳过检索")
            return empty_result

        try:
            import numpy as np

            query_vector = build_hash_embedding(query, int(self._embeddings.shape[1]))
            vector_scores = np.dot(self._embeddings, query_vector)
            exact_scores = np.array(
                [_exact_match_score(query, item) for item in self._tags],
                dtype=np.float32,
            )
            if np.any(exact_scores > 0.0):
                scores = exact_scores
            else:
                scores = vector_scores
            sorted_indices = np.argsort(scores)[::-1]
        except Exception as e:
            logger.error(f"本地向量检索失败: {e}")
            return empty_result

        search_results: list[dict[str, Any]] = []
        for index in sorted_indices:
            score = float(scores[index])
            if score < self.min_score:
                continue
            item = self._tags[int(index)]
            search_results.append(
                {
                    "tag": item.get("tag", ""),
                    "cn_name": item.get("cn_name", ""),
                    "category": item.get("category", "General"),
                    "score": round(score, 4),
                }
            )
            if len(search_results) >= self.top_k:
                break

        logger.info(f"本地向量检索完成：query='{query[:30]}' → search={len(search_results)} 条")
        return {"search": search_results, "related": []}

    async def cache_results(
        self,
        results: dict[str, list[dict[str, Any]]],
        min_score: float = 0.45,
        max_items: int = 5000,
        include_related: bool = False,
    ) -> int:
        """将在线检索结果缓存到本地 tag 向量库。"""
        async with _CACHE_WRITE_LOCK:
            items = self._filter_cache_items(results, min_score, include_related)
            if not items:
                return 0

            tags_file = self.data_dir / "danbooru_tags.json"
            existing_tags = self._load_existing_tags(tags_file)
            existing_keys = {_tag_key(str(item.get("tag", ""))) for item in existing_tags}
            available_slots = max(max_items - len(existing_tags), 0)
            if available_slots <= 0:
                logger.info(f"本地 tag 缓存已达到上限 {max_items}，跳过写入")
                return 0

            new_tags: list[dict[str, Any]] = []
            copyright_terms = _copyright_match_terms(existing_tags)
            for item in items:
                tag = str(item.get("tag", "")).strip()
                key = _tag_key(tag)
                if not tag or key in existing_keys:
                    continue
                new_tags.append(self._build_cache_tag(item, copyright_terms))
                existing_keys.add(key)
                if len(new_tags) >= available_slots:
                    break

            if not new_tags:
                return 0

            all_tags = [*existing_tags, *new_tags]
            self._save_cache_files(all_tags)
            self._tags = None
            self._embeddings = None
            self._loaded = False
            logger.info(f"已缓存 online tag 到本地向量库：新增 {len(new_tags)} 条")
            return len(new_tags)

    def _filter_cache_items(
        self,
        results: dict[str, list[dict[str, Any]]],
        min_score: float,
        include_related: bool,
    ) -> list[dict[str, Any]]:
        """过滤允许写入本地缓存的在线检索结果。"""
        items: list[dict[str, Any]] = []
        for item in results.get("search", []):
            if float(item.get("score", 0.0) or 0.0) >= min_score:
                items.append(item)
        if include_related:
            for item in results.get("related", []):
                category = str(item.get("category", "General")).lower()
                cooc_score = float(item.get("cooc_score", 0.0) or 0.0)
                if category in {"general", "meta"} and cooc_score >= min_score:
                    items.append(item)
        return items

    def _load_existing_tags(self, tags_file: Path) -> list[dict[str, Any]]:
        """读取现有本地 tag 数据。"""
        if not tags_file.exists():
            return []
        try:
            data = json.loads(tags_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取本地 tag 缓存失败，将重建缓存文件: {exc}")
            return []
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            return []
        return [item for item in tags if isinstance(item, dict)]

    def _build_cache_tag(self, item: dict[str, Any], copyright_terms: set[str] | None = None) -> dict[str, Any]:
        """构建写入本地库的在线 tag 条目。"""
        category = str(item.get("category", "General") or "General")
        cn_name = str(item.get("cn_name", "")).strip()
        aliases: list[str] = []
        if _category_key(category) == "character":
            names = _clean_character_names(item, copyright_terms or set())
            cn_name = ", ".join(names)
            aliases = names
        cached_item = {
            "tag": str(item.get("tag", "")).strip(),
            "cn_name": cn_name,
            "category": category,
            "aliases": aliases,
            "source": "online_cache",
        }
        if "score" in item:
            cached_item["score"] = round(float(item.get("score", 0.0) or 0.0), 4)
        return cached_item

    def _save_cache_files(self, tags: list[dict[str, Any]]) -> None:
        """保存 tag 列表并重建本地 hash embedding 矩阵。"""
        import numpy as np

        self.data_dir.mkdir(parents=True, exist_ok=True)
        tags_file = self.data_dir / "danbooru_tags.json"
        embeddings_file = self.data_dir / "tag_embeddings.npy"
        tmp_tags_file = self.data_dir / "danbooru_tags.tmp.json"
        tmp_embeddings_file = self.data_dir / "tag_embeddings.tmp.npy"

        embeddings = np.stack(
            [build_hash_embedding(build_tag_embedding_text(item), dim=_HASH_EMBEDDING_DIM) for item in tags]
        ).astype(np.float32)
        tmp_tags_file.write_text(json.dumps({"tags": tags}, ensure_ascii=False, indent=2), encoding="utf-8")
        np.save(tmp_embeddings_file, embeddings)
        tmp_tags_file.replace(tags_file)
        tmp_embeddings_file.replace(embeddings_file)

    async def _ensure_loaded(self) -> None:
        """懒加载 tags 和 embeddings 数据。"""
        if self._loaded:
            return

        tags_file = self.data_dir / "danbooru_tags.json"
        embeddings_file = self.data_dir / "tag_embeddings.npy"

        if not tags_file.exists():
            raise FileNotFoundError(f"Tags 文件不存在: {tags_file}")
        if not embeddings_file.exists():
            raise FileNotFoundError(f"Embedding 文件不存在: {embeddings_file}")

        logger.info(f"加载本地 tags 文件: {tags_file}")
        with open(tags_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._tags = data.get("tags", [])

        logger.info(f"加载 embedding 矩阵: {embeddings_file}")
        try:
            import numpy as np

            self._embeddings = np.load(str(embeddings_file)).astype(np.float32)
        except ImportError:
            logger.error("numpy 未安装，无法加载 embedding 矩阵")
            raise

        if self._embeddings.ndim != 2:
            raise ValueError(f"embedding 矩阵必须是二维数组，当前 shape={self._embeddings.shape}")
        if len(self._tags) != self._embeddings.shape[0]:
            raise ValueError(
                f"tags 数量与 embedding 行数不一致: tags={len(self._tags)}, rows={self._embeddings.shape[0]}"
            )

        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        self._embeddings = self._embeddings / norms

        logger.info(
            f"本地库已加载: {len(self._tags)} 个 tags，"
            f"embedding 维度 {self._embeddings.shape}"
        )
        self._loaded = True

    def is_available(self) -> bool:
        """检查本地数据文件是否可用。"""
        tags_file = self.data_dir / "danbooru_tags.json"
        embeddings_file = self.data_dir / "tag_embeddings.npy"
        return tags_file.exists() and embeddings_file.exists()
