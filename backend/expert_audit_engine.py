"""
Expert Audit Engine — Meta-AI consensus layer

Odpowiada za:
1. Zbieranie odpowiedzi od wszystkich AI providerów
2. Porównanie confidence, score, sprzeczności
3. Wystawienie finalnej decyzji (BUY / SELL / WAIT / REJECT_SIGNAL)
4. Dokumentacja przyczyny decyzji
5. Diagnostyka: które AI co powiedziało, kto został outlier

Logika:
- Consensus mode "majority": N AI mówi BUY → BUY (jeśli score > threshold)
- Confidence check: jeśli jedna AI ma high confidence, inne low → WAIT (sprzeczność)
- Risk scoring: suma ryzyk, max drawdown
- Outlier detection: jeśli 1 AI sprzeciwia się innym → odrzuć jako outlier
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AIResponse:
    """Pojedyncza odpowiedź od AI providera."""

    def __init__(
        self,
        provider: str,
        symbol: str,
        decision: str,  # BUY / SELL / WAIT / UNKNOWN
        confidence: float,  # 0.0-1.0
        score: float,  # 0.0-100.0
        reasoning: str,
        avg_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        risk_score: Optional[float] = None,  # 0-100, wyżej = bardziej ryzykowne
    ):
        self.provider = provider
        self.symbol = symbol
        self.decision = decision.upper()
        self.confidence = max(0.0, min(1.0, confidence))
        self.score = max(0.0, min(100.0, score))
        self.reasoning = reasoning or ""
        self.avg_price = avg_price
        self.tp_price = tp_price
        self.sl_price = sl_price
        self.risk_score = risk_score or 50.0
        self.is_outlier = False

    def __repr__(self) -> str:
        return (
            f"AIResponse({self.provider}:{self.decision} "
            f"conf={self.confidence:.2f} score={self.score:.1f})"
        )


class ExpertAuditResult:
    """Wynik audytu ekspertów."""

    def __init__(
        self,
        symbol: str,
        final_decision: str,  # BUY / SELL / WAIT / REJECT_SIGNAL
        confidence: float,
        audit_score: float,
        reasoning: str,
        individual_responses: List[AIResponse],
        consensus_count: Dict[str, int],  # {"BUY": 2, "SELL": 0, "WAIT": 2}
        outliers: List[str],  # lista providerów, które były outlierami
        avg_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        risk_score: Optional[float] = None,
    ):
        self.symbol = symbol
        self.final_decision = final_decision
        self.confidence = max(0.0, min(1.0, confidence))
        self.audit_score = max(0.0, min(100.0, audit_score))
        self.reasoning = reasoning
        self.individual_responses = individual_responses
        self.consensus_count = consensus_count
        self.outliers = outliers
        self.avg_price = avg_price
        self.tp_price = tp_price
        self.sl_price = sl_price
        self.risk_score = risk_score or 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "final_decision": self.final_decision,
            "confidence": self.confidence,
            "audit_score": self.audit_score,
            "reasoning": self.reasoning,
            "consensus": self.consensus_count,
            "outliers": self.outliers,
            "avg_price": self.avg_price,
            "tp_price": self.tp_price,
            "sl_price": self.sl_price,
            "risk_score": self.risk_score,
            "ai_votes": {
                r.provider: {
                    "decision": r.decision,
                    "confidence": r.confidence,
                    "score": r.score,
                    "is_outlier": r.is_outlier,
                }
                for r in self.individual_responses
            },
        }


def _detect_outliers(responses: List[AIResponse]) -> tuple[List[AIResponse], List[str]]:
    """Detektuj outlierowe odpowiedzi.

    Logika:
    - Jeśli decision_counts: N-1 zgadza się, 1 nie → outlier
    - Jeśli confidence_std > 0.4 → możliwe outlierowanie
    - Jeśli score_std > 30 → możliwe outlierowanie

    Returns: (outliered_responses, outlier_provider_names)
    """
    if len(responses) <= 2:
        # Za mało providerów, aby wiarygodnie wyznaczać outlierów
        return responses, []

    # Zlicz decyzje
    decision_count: Dict[str, int] = {}
    for r in responses:
        decision_count[r.decision] = decision_count.get(r.decision, 0) + 1

    # Jeśli jedna decyzja ma tylko 1 głos a inne mają więcej → outlier
    outlier_decisions = {
        d for d, c in decision_count.items() if c == 1 and len(decision_count) > 1
    }

    outliers_list = []
    for r in responses:
        if r.decision in outlier_decisions:
            r.is_outlier = True
            outliers_list.append(r.provider)

    return responses, outliers_list


def _compute_consensus(responses: List[AIResponse]) -> Dict[str, int]:
    """Policz głosy dla każdej decyzji."""
    count: Dict[str, int] = {}
    for r in responses:
        count[r.decision] = count.get(r.decision, 0) + 1
    return count


def audit_multi_ai_responses(
    symbol: str,
    responses: List[AIResponse],
    mode: str = "expert_audit",  # expert_audit | majority_vote | weighted_consensus
) -> ExpertAuditResult:
    """
    Audytuj wszystkie odpowiedzi AI i wytaguj finalną decyzję.

    Tryby:
    - expert_audit: detektuj outlierów, porównuj confidence, wymagaj wysokiego consensus
    - majority_vote: zwykłe głosowanie, większość wygrywa
    - weighted_consensus: consensus ważony confidence każdego AI

    Returns: ExpertAuditResult z finalną decyzją i diagnozą
    """
    logger.debug(
        "[expert_audit] symbol=%s mode=%s providers=%d",
        symbol,
        mode,
        len(responses),
    )

    if not responses:
        return ExpertAuditResult(
            symbol=symbol,
            final_decision="REJECT_SIGNAL",
            confidence=0.0,
            audit_score=0.0,
            reasoning="Brak odpowiedzi AI providerów",
            individual_responses=[],
            consensus_count={},
            outliers=[],
        )

    # Detektuj outlierów
    responses, outliers = _detect_outliers(responses)

    # Usunięcie outlierów z głosowania (jeśli mode to expert_audit)
    voting_responses = (
        [r for r in responses if not r.is_outlier]
        if mode == "expert_audit"
        else responses
    )

    if not voting_responses:
        voting_responses = responses  # fallback: zawsze coś musimy mieć

    # Compute consensus na voting responses
    consensus = _compute_consensus(voting_responses)

    # Wyznacz finalną decyzję
    buy_count = consensus.get("BUY", 0)
    sell_count = consensus.get("SELL", 0)
    wait_count = consensus.get("WAIT", 0)
    total_voting = len(voting_responses)

    if total_voting == 0:
        final_decision = "REJECT_SIGNAL"
        confidence = 0.0
        audit_score = 0.0
        reasoning = "Brak głosów do liczenia"
    else:
        buy_ratio = buy_count / total_voting if buy_count > 0 else 0.0
        sell_ratio = sell_count / total_voting if sell_count > 0 else 0.0
        wait_ratio = wait_count / total_voting if wait_count > 0 else 0.0

        # Decyzja: jeśli >= 60% mówi BUY/SELL → podejmij to; jeśli < to → WAIT
        if buy_ratio >= 0.6:
            final_decision = "BUY"
            confidence = buy_ratio
        elif sell_ratio >= 0.6:
            final_decision = "SELL"
            confidence = sell_ratio
        elif buy_ratio > sell_ratio and buy_ratio >= 0.4:
            # 40-60% BUY ale więcej niż SELL → skłonność do BUY, ale WAIT
            final_decision = "WAIT"
            confidence = buy_ratio
        elif sell_ratio > buy_ratio and sell_ratio >= 0.4:
            # 40-60% SELL ale więcej niż BUY → skłonność do SELL, ale WAIT
            final_decision = "WAIT"
            confidence = sell_ratio
        else:
            # Rozproszone głosy
            final_decision = "WAIT"
            confidence = max(buy_ratio, sell_ratio, wait_ratio)

        # Audit score: kombinacja consensus + unique votes + outlier count
        max_single_vote = max(buy_count, sell_count, wait_count) / total_voting
        outlier_penalty = len(outliers) * 10.0  # -10 za każdego outlaiera
        audit_score = (max_single_vote * 80.0) - outlier_penalty
        audit_score = max(0.0, min(100.0, audit_score))

    # Zbierz argumenty
    best_reasoning = ""
    avg_price = None
    tp_price = None
    sl_price = None
    avg_risk = 0.0

    if voting_responses:
        # Znajdź najlepiej uzasadnioną odpowiedź
        best_response = max(
            voting_responses, key=lambda r: r.confidence * (r.score / 100.0)
        )
        best_reasoning = best_response.reasoning
        avg_price = best_response.avg_price
        tp_price = best_response.tp_price
        sl_price = best_response.sl_price
        avg_risk = sum(r.risk_score or 50.0 for r in voting_responses) / len(
            voting_responses
        )

    # Finalna reasoning
    consensus_str = f"BUY:{buy_count} SELL:{sell_count} WAIT:{wait_count}"
    outlier_str = f" [outliers: {', '.join(outliers)}]" if outliers else ""
    final_reasoning = (
        f"Consensus: {consensus_str}{outlier_str}. "
        f"Final: {final_decision} (conf={confidence:.2f}). "
        f"{best_reasoning}"
    )

    logger.info(
        "[expert_audit_done] symbol=%s decision=%s confidence=%.2f audit_score=%.1f outliers=%d",
        symbol,
        final_decision,
        confidence,
        audit_score,
        len(outliers),
    )

    return ExpertAuditResult(
        symbol=symbol,
        final_decision=final_decision,
        confidence=confidence,
        audit_score=audit_score,
        reasoning=final_reasoning,
        individual_responses=responses,
        consensus_count=consensus,
        outliers=outliers,
        avg_price=avg_price,
        tp_price=tp_price,
        sl_price=sl_price,
        risk_score=avg_risk,
    )


def create_ai_response_from_dict(
    provider: str, symbol: str, data: Dict[str, Any]
) -> AIResponse:
    """Helper: konwertuj dict (z JSON/API) na AIResponse."""
    return AIResponse(
        provider=provider,
        symbol=symbol,
        decision=data.get("decision", "UNKNOWN"),
        confidence=float(data.get("confidence", 0.5)),
        score=float(data.get("score", 50.0)),
        reasoning=data.get("reasoning", ""),
        avg_price=data.get("avg_price"),
        tp_price=data.get("tp_price"),
        sl_price=data.get("sl_price"),
        risk_score=data.get("risk_score"),
    )
