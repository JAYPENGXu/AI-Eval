from __future__ import annotations

import pytest

from rag.hybrid import add_ranked_results, rrf_fusion


def chunk(chunk_id: int, *, rank: int = 1, score: float = 0.9, engine: str = "vector", content: str = "") -> dict:
    return {
        "chunk_id": chunk_id,
        "rank": rank,
        "score": score,
        "engine": engine,
        "content": content or f"chunk-{chunk_id}",
    }


class TestRrfFusion:
    def test_same_chunk_in_both_lists_ranks_highest(self):
        vector = [chunk(101, rank=1, engine="vector")]
        bm25 = [chunk(202, rank=1, engine="bm25"), chunk(101, rank=5, engine="bm25")]

        fused = rrf_fusion(bm25, vector, top_k=5, rrf_k=60)

        assert [item["chunk_id"] for item in fused] == [101, 202]
        assert fused[0]["sources"]["vector"]["rank"] == 1
        assert fused[0]["sources"]["bm25"]["rank"] == 5

    def test_rrf_score_is_sum_of_reciprocal_ranks(self):
        vector = [chunk(101, rank=2, engine="vector")]
        bm25 = [chunk(101, rank=4, engine="bm25")]

        fused = rrf_fusion(bm25, vector, top_k=1, rrf_k=10)

        expected = (1 / (10 + 2)) + (1 / (10 + 4))
        assert fused[0]["chunk_id"] == 101
        assert fused[0]["rrf_score"] == pytest.approx(expected)
        assert fused[0]["score"] == pytest.approx(expected)

    def test_top_k_limits_output(self):
        vector = [chunk(1, rank=1), chunk(2, rank=2), chunk(3, rank=3)]
        bm25 = [chunk(4, rank=1), chunk(5, rank=2)]

        fused = rrf_fusion(bm25, vector, top_k=2, rrf_k=60)

        assert len(fused) == 2
        assert fused[0]["rank"] == 1
        assert fused[1]["rank"] == 2

    def test_vector_only_results_still_fuse(self):
        vector = [chunk(11, rank=1), chunk(12, rank=2)]

        fused = rrf_fusion([], vector, top_k=5, rrf_k=60)

        assert [item["chunk_id"] for item in fused] == [11, 12]
        assert fused[0]["engine"] == "hybrid_rrf"
        assert fused[0]["sources"] == {"vector": {"rank": 1, "score": 0.9, "engine": "vector", "matched_terms": []}}

    def test_bm25_only_results_still_fuse(self):
        bm25 = [chunk(21, rank=1, engine="bm25", score=3.5)]

        fused = rrf_fusion(bm25, [], top_k=5, rrf_k=60)

        assert fused[0]["chunk_id"] == 21
        assert fused[0]["sources"]["bm25"]["score"] == 3.5

    def test_missing_rank_uses_enumeration_fallback(self):
        vector = [{"chunk_id": 31, "score": 0.8, "engine": "vector", "content": "a"}]
        bm25 = [{"chunk_id": 32, "score": 1.2, "engine": "bm25", "content": "b"}]

        fused = rrf_fusion(bm25, vector, top_k=5, rrf_k=60)
        by_id = {item["chunk_id"]: item for item in fused}

        assert by_id[31]["sources"]["vector"]["rank"] == 1
        assert by_id[32]["sources"]["bm25"]["rank"] == 1

    def test_higher_rrf_k_reduces_relative_score_gap(self):
        vector = [chunk(101, rank=1), chunk(102, rank=3)]
        bm25 = [chunk(102, rank=1)]

        tight = rrf_fusion(bm25, vector, top_k=2, rrf_k=1)
        loose = rrf_fusion(bm25, vector, top_k=2, rrf_k=100)

        tight_gap = tight[0]["rrf_score"] - tight[1]["rrf_score"]
        loose_gap = loose[0]["rrf_score"] - loose[1]["rrf_score"]
        assert loose_gap < tight_gap


class TestAddRankedResults:
    def test_merges_sources_without_overwriting_existing_chunk(self):
        fused: dict[int, dict] = {}
        add_ranked_results(fused, [chunk(101, rank=1, engine="vector")], "vector", 60)
        add_ranked_results(fused, [chunk(101, rank=3, engine="bm25")], "bm25", 60)

        merged = fused[101]
        assert set(merged["sources"]) == {"vector", "bm25"}
        assert merged["content"] == "chunk-101"
        assert merged["rrf_score"] == pytest.approx((1 / 61) + (1 / 63))
