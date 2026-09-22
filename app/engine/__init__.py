from .body_score import compute_body_score
from .common import BodyMetrics, BodyMetricsInput, OutOfRangeReading
from .reference_ranges import Range, reference_ranges_for
from .science import compute_science_metrics
from .xiaomi import compute_xiaomi_metrics

ALGORITHMS = {
    "xiaomi": compute_xiaomi_metrics,
    "science": compute_science_metrics,
}


def compute_metrics(algorithm: str, data: BodyMetricsInput) -> BodyMetrics:
    """Despacha o cálculo para o motor do algoritmo escolhido (RF06)."""
    try:
        engine = ALGORITHMS[algorithm]
    except KeyError:
        raise ValueError(f"unknown algorithm: {algorithm!r} (expected one of {sorted(ALGORITHMS)})") from None
    return engine(data)


__all__ = [
    "ALGORITHMS",
    "BodyMetrics",
    "BodyMetricsInput",
    "OutOfRangeReading",
    "Range",
    "compute_body_score",
    "compute_metrics",
    "compute_science_metrics",
    "compute_xiaomi_metrics",
    "reference_ranges_for",
]
