"""Metric cross-validator — dual-source variance check for any metric.

Generalized from PE forward validation. Works with any metric supported by
the registered DataSourceAdapters (fwd_pe, ttm_pe, pb, ps, roe, etc.).

Cage has done this manually for 5 months. Automating a known workflow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from cagent_os.data_layer.adapter import DataSourceAdapter

logger = logging.getLogger(__name__)

VARIANCE_THRESHOLD = 0.05


@dataclass
class VerifiedMetric:
    value: float | None
    confidence: float
    sources: list[str] = field(default_factory=list)
    excluded_sources: list[str] = field(default_factory=list)
    verification_level: str = "single_source"
    warnings: list[str] = field(default_factory=list)


class MetricCrossValidator:

    def __init__(self, *sources: DataSourceAdapter, threshold: float = VARIANCE_THRESHOLD) -> None:
        self._sources = sources
        self._threshold = threshold

    async def verify(self, ticker: str, metric: str) -> VerifiedMetric:
        results: dict[str, float] = {}
        errors: dict[str, str] = {}
        for src in self._sources:
            try:
                raw = await src.fetch(metric, ticker=ticker)
                if isinstance(raw.value, (int, float)) and raw.value is not None:
                    results[src.name] = float(raw.value)
                else:
                    errors[src.name] = f"non-numeric: {raw.value}"
            except Exception as exc:
                errors[src.name] = str(exc)
        return self._evaluate(results, errors)

    def _evaluate(self, results: dict[str, float], errors: dict[str, str]) -> VerifiedMetric:
        if len(results) < 2:
            if results:
                name, value = next(iter(results.items()))
                return VerifiedMetric(value=value, confidence=0.5, sources=[name],
                    verification_level="single_source",
                    warnings=[f"{k}: {v}" for k, v in errors.items()])
            return VerifiedMetric(value=None, confidence=0.0, verification_level="failed",
                warnings=[f"{k}: {v}" for k, v in errors.items()])
        values = list(results.values())
        names = list(results.keys())
        variance = abs(max(values) - min(values)) / max(abs(min(values)), 1e-10)
        if variance <= self._threshold:
            return VerifiedMetric(value=round(sum(values) / len(values), 2),
                confidence=0.85, sources=names, verification_level="dual_source")
        avg_all = sum(values) / len(values)
        worst = max(names, key=lambda n: abs(results[n] - avg_all))
        remaining = {n: v for n, v in zip(names, values) if n != worst}
        warnings = [f"{worst} deviates >{self._threshold:.0%}, excluded"]
        if len(remaining) >= 2:
            return VerifiedMetric(value=round(sum(remaining.values()) / len(remaining), 2),
                confidence=0.7, sources=list(remaining.keys()),
                excluded_sources=[worst],
                verification_level="dual_source_with_outlier", warnings=warnings)
        return VerifiedMetric(value=values[0], confidence=0.4, sources=[names[0]],
            excluded_sources=[worst],
            verification_level="single_source_after_outlier", warnings=warnings)
