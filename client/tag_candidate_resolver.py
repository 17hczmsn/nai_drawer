"""Tag 候选检索分发器。

根据配置选择 online/local 模式，统一调度 Tag 检索请求。
在线模式失败时自动降级到本地模式（如果可用）。
"""

from __future__ import annotations

from typing import Any

from src.app.plugin_system.api.log_api import get_logger

from ..config import NaiDrawerConfig
from .danbooru_online_retriever import DanbooruOnlineRetriever
from .tag_retriever import TagRetriever

logger = get_logger("nai_drawer.tag_candidate_resolver")


class TagCandidateResolver:
    """根据配置路由 Tag 检索请求。

    支持 online（HF Space API）和 local（本地向量）两种模式。
    在线模式失败时自动降级到本地模式（如果配置了 local 数据）。
    """

    def __init__(self, config: NaiDrawerConfig) -> None:
        """初始化分发器。

        Args:
            config: 插件配置实例
        """
        self.config = config
        self._online_retriever: DanbooruOnlineRetriever | None = None
        self._local_retriever: TagRetriever | None = None

    async def resolve(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """获取 Tag 候选。

        Args:
            query: 用户自然语言描述

        Returns:
            {
                'search': [{'tag': ..., 'cn_name': ..., 'score': ..., 'category': ...}, ...],
                'related': [{'tag': ..., 'cn_name': ..., 'cooc_score': ..., 'category': ...}, ...],
            }
            降级或失败时返回空字典 {}
        """
        mode = self.config.tag_retriever.mode.lower()

        try:
            if mode == "online":
                result = await self._resolve_online(query)
                await self._cache_online_result(result)
                # 在线模式无结果时尝试降级到本地
                if not result.get("search") and not result.get("related"):
                    logger.info("在线检索无结果，尝试降级到本地模式")
                    local_result = await self._resolve_local(query)
                    if local_result.get("search"):
                        return local_result
                return result
            elif mode == "local":
                return await self._resolve_local(query)
            else:
                logger.error(f"未知的检索模式: {mode}，跳过 Tag 检索")
                return {}
        except Exception as e:
            logger.warning(f"Tag 检索失败 ({mode} 模式)，继续流程但不使用候选: {e}")
            # 在线模式异常时尝试降级
            if mode == "online":
                try:
                    local_result = await self._resolve_local(query)
                    if local_result.get("search"):
                        logger.info("在线检索异常，降级到本地模式成功")
                        return local_result
                except Exception as local_e:
                    logger.warning(f"本地降级也失败: {local_e}")
            return {}

    def format_candidates(self, results: dict[str, list[dict[str, Any]]]) -> str:
        """将检索结果格式化为可注入系统提示词的文本块。

        Args:
            results: resolve() 的返回值

        Returns:
            格式化的 <tag_candidates> 文本块；无结果时返回空字符串
        """
        if not results:
            return ""

        mode = self.config.tag_retriever.mode.lower()

        if mode == "online":
            retriever = self._get_online_retriever()
            return retriever.format_candidates(results)
        elif mode == "local":
            # 本地模式使用自己的格式化
            search_items = results.get("search", [])
            if not search_items:
                return ""

            lines: list[str] = ["<tag_candidates>"]
            lines.append("## 语义匹配（与用户描述直接相关，优先选用）")
            for item in search_items:
                cn = item.get("cn_name", "")
                tag = item["tag"]
                score = item.get("score", 0.0)
                cn_part = f"{cn} → " if cn else ""
                lines.append(f"- {cn_part}{tag} (相似度 {score:.2f})")

            lines.append("</tag_candidates>")
            return "\n".join(lines)

        return ""

    def _get_online_retriever(self) -> DanbooruOnlineRetriever:
        """获取或创建在线检索器实例（懒初始化）。"""
        if self._online_retriever is None:
            cfg = self.config.tag_retriever
            self._online_retriever = DanbooruOnlineRetriever(
                base_url=cfg.api_url,
                timeout=cfg.timeout,
                search_limit=cfg.search_limit,
                search_top_k=cfg.search_top_k,
                related_limit=cfg.related_limit,
                related_seed_count=cfg.related_seed_count,
                show_nsfw=cfg.show_nsfw,
                popularity_weight=cfg.popularity_weight,
            )
        return self._online_retriever

    def _get_local_retriever(self) -> TagRetriever:
        """获取或创建本地检索器实例（懒初始化）。"""
        if self._local_retriever is None:
            cfg = self.config.tag_retriever
            self._local_retriever = TagRetriever(top_k=cfg.top_k, min_score=cfg.min_score)
        return self._local_retriever

    async def _resolve_online(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """在线模式检索。"""
        retriever = self._get_online_retriever()
        logger.info(f"使用在线模式检索: '{query[:50]}'")
        return await retriever.retrieve(query)

    async def _cache_online_result(self, result: dict[str, list[dict[str, Any]]]) -> None:
        """按配置将 online search 结果缓存到本地向量库。"""
        cfg = self.config.tag_retriever
        if not getattr(cfg, "cache_online_results", False):
            return
        if not result.get("search") and not result.get("related"):
            return
        retriever = self._get_local_retriever()
        await retriever.cache_results(
            result,
            min_score=float(getattr(cfg, "cache_min_score", 0.45)),
            max_items=int(getattr(cfg, "cache_max_items", 5000)),
            include_related=bool(getattr(cfg, "cache_related_results", False)),
        )

    async def _resolve_local(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """本地模式检索。"""
        retriever = self._get_local_retriever()
        logger.info(f"使用本地模式检索: '{query[:50]}'")
        return await retriever.retrieve(query)
