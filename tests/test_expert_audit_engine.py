"""
Testy dla expert_audit_engine.py

Scenariusze:
- consensus voting: 3 BUY, 1 WAIT → BUY
- outlier detection: 3 BUY, 1 SELL → SELL jest outlier
- low confidence: rozproszone głosy → WAIT
- sprzeczne confidence: jedyne high conf → WAIT (sprzeczność)
"""

import pytest

from backend.expert_audit_engine import (
    AIResponse,
    ExpertAuditResult,
    _compute_consensus,
    _detect_outliers,
    audit_multi_ai_responses,
    create_ai_response_from_dict,
)


class TestAIResponse:
    """Test klasy AIResponse."""

    def test_ai_response_creation(self):
        """Test tworzenia AIResponse."""
        resp = AIResponse(
            provider="local",
            symbol="BTCUSDC",
            decision="BUY",
            confidence=0.9,
            score=85.0,
            reasoning="Strong uptrend",
        )
        assert resp.provider == "local"
        assert resp.symbol == "BTCUSDC"
        assert resp.decision == "BUY"
        assert resp.confidence == 0.9
        assert resp.score == 85.0
        assert resp.is_outlier is False

    def test_confidence_clamped_0_to_1(self):
        """Test że confidence jest zaciskane do 0-1."""
        resp = AIResponse(
            provider="test",
            symbol="BTCUSDC",
            decision="BUY",
            confidence=1.5,  # powinno być zaciskane
            score=50,
            reasoning="",
        )
        assert resp.confidence == 1.0

        resp2 = AIResponse(
            provider="test",
            symbol="BTCUSDC",
            decision="BUY",
            confidence=-0.5,
            score=50,
            reasoning="",
        )
        assert resp2.confidence == 0.0

    def test_decision_uppercase(self):
        """Test że decision jest zawsze uppercase."""
        resp = AIResponse(
            provider="test",
            symbol="BTCUSDC",
            decision="wait",
            confidence=0.5,
            score=50,
            reasoning="",
        )
        assert resp.decision == "WAIT"


class TestDetectOutliers:
    """Test detektowania outlierów."""

    def test_no_outliers_unanimous(self):
        """Test gdy wszyscy zgadzają się."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong"),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "Good"),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, "Strong"),
        ]
        responses, outliers = _detect_outliers(responses)
        assert len(outliers) == 0
        assert all(not r.is_outlier for r in responses)

    def test_outlier_one_disagree(self):
        """Test gdy 3 mówią BUY, 1 mówi SELL → SELL jest outlier."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong"),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "Good"),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, "Strong"),
            AIResponse("openai", "BTC", "SELL", 0.6, 40, "Caution"),
        ]
        responses, outliers = _detect_outliers(responses)
        assert len(outliers) == 1
        assert outliers[0] == "openai"
        assert any(r.is_outlier for r in responses if r.provider == "openai")

    def test_outlier_two_providers(self):
        """Test gdy >= 2 providery zgadzają się — brak outliera (niedostateczna większość)."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong"),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "Good"),
            AIResponse("groq", "BTC", "SELL", 0.8, 70, "Caution"),
            AIResponse("openai", "BTC", "SELL", 0.75, 65, "Caution"),
        ]
        responses, outliers = _detect_outliers(responses)
        # 2 BUY, 2 SELL — żaden nie jest single vote — brak outliera
        assert len(outliers) == 0


class TestComputeConsensus:
    """Test liczenia consensus."""

    def test_consensus_count(self):
        """Test zliczania głosów."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, ""),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, ""),
            AIResponse("groq", "BTC", "WAIT", 0.7, 50, ""),
        ]
        consensus = _compute_consensus(responses)
        assert consensus.get("BUY") == 2
        assert consensus.get("WAIT") == 1
        assert consensus.get("SELL", 0) == 0


class TestAuditMultiAI:
    """Test audytu multi-AI responses."""

    def test_unanimous_buy_decision(self):
        """Test gdy wszyscy mówią BUY → final decision = BUY."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong uptrend"),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "Positive signals"),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, "Bullish"),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)

        assert result.final_decision == "BUY"
        assert result.confidence >= 0.8
        assert len(result.outliers) == 0
        assert result.symbol == "BTCUSDC"

    def test_majority_buy_with_outlier(self):
        """Test gdy 3 mówią BUY, 1 SELL → BUY wins, SELL is outlier."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong"),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "Good"),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, "Strong"),
            AIResponse("openai", "BTC", "SELL", 0.6, 40, "Caution"),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)

        assert result.final_decision == "BUY"
        assert "openai" in result.outliers
        assert result.confidence >= 0.6

    def test_split_vote_returns_wait(self):
        """Test gdy 2 BUY, 2 SELL → WAIT (brak consensus)."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.7, 70, ""),
            AIResponse("gemini", "BTC", "BUY", 0.6, 60, ""),
            AIResponse("groq", "BTC", "SELL", 0.75, 75, ""),
            AIResponse("openai", "BTC", "SELL", 0.8, 80, ""),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)

        assert result.final_decision == "WAIT"
        # Split vote: brak wyraźnego consensusu

    def test_empty_responses_reject_signal(self):
        """Test gdy brak responseów → REJECT_SIGNAL."""
        result = audit_multi_ai_responses("BTCUSDC", [])

        assert result.final_decision == "REJECT_SIGNAL"
        assert result.confidence == 0.0

    def test_audit_score_calculation(self):
        """Test że audit_score jest liczony."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, ""),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, ""),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, ""),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)

        assert result.audit_score > 0.0
        assert result.audit_score <= 100.0

    def test_to_dict(self):
        """Test konwersji do dict."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "Strong"),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)
        d = result.to_dict()

        assert d["symbol"] == "BTCUSDC"
        assert d["final_decision"] in ("BUY", "SELL", "WAIT", "REJECT_SIGNAL")
        assert "consensus" in d
        assert "ai_votes" in d

    def test_create_ai_response_from_dict(self):
        """Test tworzenia AIResponse z dict."""
        data = {
            "decision": "BUY",
            "confidence": 0.85,
            "score": 88.0,
            "reasoning": "Bullish",
        }
        resp = create_ai_response_from_dict("gemini", "BTCUSDC", data)

        assert resp.provider == "gemini"
        assert resp.symbol == "BTCUSDC"
        assert resp.decision == "BUY"
        assert resp.confidence == 0.85

    def test_majority_vote_mode(self):
        """Test majority_vote mode (bez outlier detection)."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.8, 80, ""),
            AIResponse("gemini", "BTC", "SELL", 0.8, 80, ""),
            AIResponse("groq", "BTC", "BUY", 0.8, 80, ""),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses, mode="majority_vote")

        # 2 BUY, 1 SELL → BUY
        assert result.final_decision == "BUY"

    def test_consensus_with_risk_scores(self):
        """Test że risk_score jest agregowany."""
        responses = [
            AIResponse("local", "BTC", "BUY", 0.9, 90, "", risk_score=30.0),
            AIResponse("gemini", "BTC", "BUY", 0.85, 88, "", risk_score=40.0),
            AIResponse("groq", "BTC", "BUY", 0.88, 87, "", risk_score=50.0),
        ]
        result = audit_multi_ai_responses("BTCUSDC", responses)

        assert result.risk_score is not None
        assert 30.0 <= result.risk_score <= 50.0  # średnia z zakresu
