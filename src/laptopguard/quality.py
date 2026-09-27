from dataclasses import dataclass


@dataclass(frozen=True)
class FrameMetrics:
    brightness: float
    sharpness: float
    face_count: int


def acceptable(
    metrics: FrameMetrics,
    min_brightness: float = 45.0,
    min_sharpness: float = 90.0,
    require_face: bool = True,
) -> bool:
    return (
        metrics.brightness >= min_brightness
        and metrics.sharpness >= min_sharpness
        and (metrics.face_count > 0 if require_face else True)
    )
