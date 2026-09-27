from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
import shutil
import subprocess
from typing import Callable, Iterable

import cv2

from .quality import FrameMetrics, acceptable


CASCADE_FILENAME = 'haarcascade_frontalface_default.xml'
SYSTEM_CASCADE_PATHS = (
    Path('/usr/share/opencv4/haarcascades') / CASCADE_FILENAME,
    Path('/usr/share/opencv/haarcascades') / CASCADE_FILENAME,
)


@dataclass(frozen=True)
class CaptureResult:
    path: Path
    metrics: FrameMetrics
    frames_seen: int


def _find_face_cascade() -> Path | None:
    data = getattr(cv2, 'data', None)
    haarcascades = getattr(data, 'haarcascades', None) if data is not None else None
    candidates = []
    if haarcascades:
        candidates.append(Path(haarcascades) / CASCADE_FILENAME)
    candidates.extend(SYSTEM_CASCADE_PATHS)
    return next((path for path in candidates if path.is_file()), None)


def _face_detector():
    cascade = _find_face_cascade()
    if cascade is None:
        return None
    detector = cv2.CascadeClassifier(str(cascade))
    return None if detector.empty() else detector


def _device_name(index: int) -> str:
    path = Path(f'/sys/class/video4linux/video{index}/name')
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return f'video{index}'




def _color_score(index: int) -> int:
    if not shutil.which('v4l2-ctl'):
        return 0
    try:
        result = subprocess.run(
            ['v4l2-ctl', f'--device=/dev/video{index}', '--list-formats-ext'],
            capture_output=True, text=True, timeout=3, check=False,
        )
        text = result.stdout.upper()
        if any(fmt in text for fmt in ("'MJPG'", "'YUYV'", "'NV12'", "'RGB3'")):
            return 2
        if any(fmt in text for fmt in ("'GREY'", "'Y10 '", "'Y12 '")):
            return -2
    except Exception:
        pass
    return 0

def _probe_camera(index: int) -> bool:
    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return False
        for _ in range(3):
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, 'size', 0) > 0:
                return True
        return False
    finally:
        cap.release()


def camera_indices() -> list[int]:
    out = []
    for path in sorted(Path('/dev').glob('video*')):
        suffix = path.name.removeprefix('video')
        if suffix.isdigit():
            out.append(int(suffix))
    return out


def choose_camera(indices: Iterable[int] | None = None, name_provider: Callable[[int], str] = _device_name, probe: Callable[[int], bool] = _probe_camera, color_score_provider: Callable[[int], int] = _color_score) -> int | None:
    candidates = list(indices if indices is not None else camera_indices())
    ranked = sorted(candidates, key=lambda i: (any(token in name_provider(i).lower() for token in (' ir', 'infrared', 'depth')), -color_score_provider(i), i))
    for index in ranked:
        try:
            if probe(index):
                return index
        except Exception:
            continue
    return None


def measure_frame(frame, detect_faces: bool = True) -> FrameMetrics:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    face_count = 0
    if detect_faces:
        detector = _face_detector()
        if detector is not None:
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            face_count = len(faces)
    return FrameMetrics(brightness, sharpness, face_count)


def capture_best(
    output_path: Path,
    camera_index: int = -1,
    max_seconds: float = 5.0,
    min_brightness: float = 45.0,
    min_sharpness: float = 90.0,
    require_face: bool = True,
) -> CaptureResult | None:
    output_path = Path(output_path)
    selected = choose_camera() if camera_index is None or int(camera_index) < 0 else int(camera_index)
    if selected is None:
        return None
    deadline = time.monotonic() + max_seconds
    cap = None
    while time.monotonic() < deadline:
        candidate = cv2.VideoCapture(selected)
        if candidate.isOpened():
            cap = candidate
            break
        candidate.release()
        time.sleep(0.15)
    if cap is None:
        return None
    frames = 0
    best = None
    best_score = float('-inf')
    try:
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.03)
                continue
            frames += 1
            metrics = measure_frame(frame, detect_faces=require_face)
            if acceptable(metrics, min_brightness, min_sharpness, require_face):
                score = metrics.sharpness + metrics.brightness * 0.25
                if score > best_score:
                    best_score = score
                    best = (frame.copy(), metrics)
            if best is not None and frames >= 8:
                break
        if best is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame, metrics = best
        if not cv2.imwrite(str(output_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 94]):
            return None
        return CaptureResult(output_path, metrics, frames)
    finally:
        cap.release()
