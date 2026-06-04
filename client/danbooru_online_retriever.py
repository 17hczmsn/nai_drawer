"""在线 Danbooru Tag 检索服务。

基于 DanbooruSearchOnline HF Space API，提供语义匹配和共现推荐双重候选。
API 文档：https://huggingface.co/spaces/sakizuki/DanbooruSearchOnline
"""

from __future__ import annotations

from typing import Any

import httpx

from src.app.plugin_system.api.log_api import get_logger

logger = get_logger("nai_drawer.danbooru_online_retriever")

_DEFAULT_BASE_URL = "https://sakizuki-danboorusearch.hf.space/api"
# HuggingFace Spaces 冷启动较慢，首次请求可能需要较长时间
_DEFAULT_TIMEOUT = 90.0


class DanbooruOnlineRetriever:
    """基于 DanbooruSearchOnline API 的在线标签检索器。

    同时利用 /search（语义匹配）和 /related（共现推荐）双重候选，
    返回结构化的检索结果供格式化注入系统提示词。
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        search_limit: int = 30,
        search_top_k: int = 5,
        related_limit: int = 20,
        related_seed_count: int = 8,
        show_nsfw: bool = True,
        popularity_weight: float = 0.15,
    ) -> None:
        """初始化在线检索器。

        Args:
            base_url: DanbooruSearchOnline API 基础地址
            timeout: 请求超时（秒）
            search_limit: /search 端点返回上限
            search_top_k: /search 端点每分词段召回数
            related_limit: /related 端点返回上限
            related_seed_count: 用多少个 search 结果作为 related 的种子
            show_nsfw: 是否包含 NSFW 标签
            popularity_weight: 标签热度权重 [0, 1]
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.search_limit = search_limit
        self.search_top_k = search_top_k
        self.related_limit = related_limit
        self.related_seed_count = related_seed_count
        self.show_nsfw = show_nsfw
        self.popularity_weight = popularity_weight

    async def retrieve(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """检索与查询最相关的标签，同时返回语义匹配和共现推荐。

        Args:
            query: 用户自然语言描述（中文优化）

        Returns:
            {
                "search": [{"tag": ..., "cn_name": ..., "score": ..., "category": ...}, ...],
                "related": [{"tag": ..., "cn_name": ..., "cooc_score": ..., "category": ...}, ...],
            }
            失败时返回空结构 {"search": [], "related": []}
        """
        empty_result: dict[str, list[dict[str, Any]]] = {"search": [], "related": []}

        if not query or not query.strip():
            return empty_result

        # 第一步：语义检索
        search_resp = await self._search(query)
        if not search_resp or not search_resp.get("results"):
            logger.warning(f"DanbooruOnline search 无结果，query='{query[:30]}'")
            return empty_result

        search_results = [
            {
                "tag": item["tag"],
                "cn_name": item.get("cn_name", ""),
                "score": item.get("final_score", 0.0),
                "category": item.get("category", "General"),
            }
            for item in search_resp["results"]
        ]

        # 客户端侧截断（确保不超过 search_top_k）
        search_results = search_results[: self.search_top_k]

        # 第二步：取 top-N 标签作为种子，获取共现推荐
        seed_tags = [r["tag"] for r in search_results[: self.related_seed_count]]
        related_results: list[dict[str, Any]] = []

        if seed_tags:
            related_resp = await self._related(seed_tags)
            if related_resp:
                # 去重：排除已在 search 结果中的标签；共现推荐只保留通用画面标签。
                # /related 容易带出同作品其它角色或作品标签（如 helia），会干扰用户点名角色。
                search_tag_set = {r["tag"] for r in search_results}
                related_results = [
                    {
                        "tag": item["tag"],
                        "cn_name": item.get("cn_name", ""),
                        "cooc_score": item.get("cooc_score", 0.0),
                        "category": item.get("category", "General"),
                    }
                    for item in related_resp
                    if item["tag"] not in search_tag_set
                    and str(item.get("category", "General")).lower() in {"general", "meta"}
                ]

        logger.info(
            f"DanbooruOnline 检索完成：query='{query[:30]}' → "
            f"search={len(search_results)} 条, related={len(related_results)} 条"
        )

        return {"search": search_results, "related": related_results}

    def format_candidates(self, results: dict[str, list[dict[str, Any]]]) -> str:
        """将检索结果格式化为可注入 LLM 模板的文本块。

        Args:
            results: retrieve() 的返回值

        Returns:
            格式化的 <tag_candidates> 文本块；无结果时返回空字符串
        """
        search_items = results.get("search", [])
        related_items = results.get("related", [])

        if not search_items and not related_items:
            return ""

        lines: list[str] = ["<tag_candidates>"]

        # 语义匹配部分
        if search_items:
            lines.append("## 语义匹配（与用户描述直接相关，优先选用）")
            for item in search_items:
                cn = item.get("cn_name", "")
                tag = item["tag"]
                category = item.get("category", "")
                score = item.get("score", 0.0)
                cn_part = f"{cn} → " if cn else ""
                lines.append(f"- {cn_part}{tag} [{category}] (相关度 {score:.2f})")

        # 共现推荐部分
        if related_items:
            lines.append("")
            lines.append("## 共现推荐（与上述标签在真实画作中经常搭配出现）")
            for item in related_items:
                cn = item.get("cn_name", "")
                tag = item["tag"]
                category = item.get("category", "")
                cooc = item.get("cooc_score", 0.0)
                cn_part = f"{cn} → " if cn else ""
                lines.append(f"- {cn_part}{tag} [{category}] (共现度 {cooc:.2f})")

        lines.append("</tag_candidates>")

        return "\n".join(lines)

    async def _search(self, query: str) -> dict[str, Any] | None:
        """调用 /search 端点进行语义标签检索。

        Args:
            query: 用户自然语言描述

        Returns:
            API 响应字典，包含 results 等字段；失败返回 None
        """
        url = f"{self.base_url}/search"
        payload: dict[str, Any] = {
            "query": query,
            "top_k": self.search_top_k,
            "limit": self.search_limit,
            "popularity_weight": self.popularity_weight,
            "show_nsfw": self.show_nsfw,
            "use_segmentation": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException:
            logger.warning(f"DanbooruOnline search 超时 (>{self.timeout}s)，query='{query[:30]}'")
            return None
        except Exception as e:
            logger.warning(f"DanbooruOnline search 失败: {e}")
            return None

    async def _related(self, tags: list[str]) -> list[dict[str, Any]] | None:
        """调用 /related 端点获取共现标签推荐。

        Args:
            tags: 种子标签列表（Danbooru 英文名）

        Returns:
            推荐标签列表；失败返回 None
        """
        if not tags:
            return []

        url = f"{self.base_url}/related"
        payload: dict[str, Any] = {
            "tags": tags,
            "limit": self.related_limit,
            "show_nsfw": self.show_nsfw,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException:
            logger.warning(f"DanbooruOnline related 超时 (>{self.timeout}s)")
            return None
        except Exception as e:
            logger.warning(f"DanbooruOnline related 失败: {e}")
            return None
