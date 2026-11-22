"""Resilience rules. Owner: Neil (C).

Patterns: circuit breaker / retry (S11, Sprint 1); health checks and saga (Sprint 2).
"""

from tc_detector.rules.resilience.circuit_breaker import detect as detect_circuit_breaker

__all__ = ["detect_circuit_breaker"]
