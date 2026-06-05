"""RAG pipeline integration tests — search + guard + contract."""

import pytest
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.action_pipeline import ActionPipeline
from core.adapters.knowledge_search import search


class TestRAGPipeline:
    """End-to-end: knowledge search → contract guard."""

    def test_keyword_search_finds_public_docs(self):
        results = search("量子计算", mode="keyword")
        assert len(results) > 0
        assert any("faq.md" in r["file"] for r in results)

    def test_semantic_search_finds_related_content(self):
        results = search("微服务", mode="semantic")
        # Semantic search should find architecture.md which doesn't literally contain "微服务"
        found_arch = any("architecture.md" in r["file"] for r in results)
        found_faq = any("faq.md" in r["file"] for r in results)
        assert found_arch or found_faq  # At least one relevant doc

    def test_guard_blocks_hr_docs(self):
        bp = DynamicBlueprint(blueprint_defaults())
        bp.apply_proposal("execution_autonomy", "FULL")
        p = ActionPipeline(bp, trust=0.30)

        results = search("裁员", mode="keyword")
        filtered = p.guard_post_retrieval("knowledge_search", results)
        for r in filtered:
            if "layoff" in r.get("file", ""):
                assert "不可访问" in r.get("content", "")

    def test_guard_allows_whitelisted_docs(self):
        bp = DynamicBlueprint(blueprint_defaults())
        bp.apply_proposal("execution_autonomy", "FULL")
        p = ActionPipeline(bp, trust=0.30)

        results = search("架构", mode="keyword")
        filtered = p.guard_post_retrieval("knowledge_search", results)
        for r in filtered:
            if "architecture.md" in r.get("file", ""):
                assert "不可访问" not in r.get("content", "")

    def test_empty_search_returns_empty(self):
        from core.adapters.knowledge_search import clear_cache
        clear_cache()
        results = search("xyzzy_nonexistent_term_12345", mode="keyword")
        assert results == []

    def test_trust_gate_blocks_low_trust(self):
        bp = DynamicBlueprint(blueprint_defaults())
        p = ActionPipeline(bp, trust=0.05)
        result = p.check("knowledge_search")
        assert not result["allowed"]

    def test_trust_gate_allows_sufficient_trust(self):
        bp = DynamicBlueprint(blueprint_defaults())
        p = ActionPipeline(bp, trust=0.30)
        result = p.check("knowledge_search")
        assert result["allowed"]

    def test_blocked_keyword_in_content_triggers_guard(self):
        bp = DynamicBlueprint(blueprint_defaults())
        bp.apply_proposal("execution_autonomy", "FULL")
        p = ActionPipeline(bp, trust=0.30)

        mock = [{"file": "public_docs/safe.md", "content": "机密：这份文档包含裁员计划..."}]
        filtered = p.guard_post_retrieval("knowledge_search", mock)
        assert "SYSTEM" in filtered[0]["content"]  # Replaced with block message

    def test_clean_content_passes_guard(self):
        bp = DynamicBlueprint(blueprint_defaults())
        bp.apply_proposal("execution_autonomy", "FULL")
        p = ActionPipeline(bp, trust=0.30)

        mock = [{"file": "public_docs/safe.md", "content": "量子计算是一种新型计算范式。"}]
        filtered = p.guard_post_retrieval("knowledge_search", mock)
        assert "不可访问" not in filtered[0]["content"]

    def test_max_results_capped(self):
        results = search("计算", mode="keyword")
        assert len(results) <= 5  # max_results default

    def test_keyword_fallback_when_semantic_model_unavailable(self):
        """Keyword mode should always work even without embedding."""
        results = search("量子计算", mode="keyword")
        assert len(results) > 0
