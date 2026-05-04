"""
Backward compatibility shim.

신규 경로: agents.summary.summary_agent
기존 import를 깨지 않기 위해 재내보낸다.
"""

from agents.summary.summary_agent import SummaryAgent, SummaryResult

__all__ = ["SummaryAgent", "SummaryResult"]

