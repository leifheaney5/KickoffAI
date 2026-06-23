"""Tests for the vision pipeline stepping API used by live webcam analysis."""

import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeCapture:
    def __init__(self, _source):
        self.frames = [
            np.zeros((12, 16, 3), dtype=np.uint8),
            np.ones((12, 16, 3), dtype=np.uint8),
            np.full((12, 16, 3), 2, dtype=np.uint8),
        ]
        self.i = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        # Values match the constants defined in _fake_cv2_module below.
        return {5: 30.0, 3: 16, 4: 12}.get(prop, 0)

    def read(self):
        if self.i >= len(self.frames):
            return False, None
        frame = self.frames[self.i]
        self.i += 1
        return True, frame

    def release(self):
        self.released = True


class _FakeDetector:
    def track(self, _frame):
        from vision.detection import Detection

        return [Detection("ball", 0.9, (6, 4, 8, 6))]


def _fake_cv2_module():
    return types.SimpleNamespace(
        VideoCapture=_FakeCapture,
        CAP_PROP_FPS=5,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
    )


def test_match_analyzer_step_api(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "cv2", _fake_cv2_module())

    from vision import MatchAnalyzer, PipelineConfig

    cfg = PipelineConfig(
        frame_stride=2,
        max_frames_recorded=1,
        ocr_enabled=False,
        output_path=str(tmp_path / "match_stats.json"),
    )
    analyzer = MatchAnalyzer(cfg)
    analyzer.detector = _FakeDetector()

    analyzer.open(0)
    first = analyzer.step()
    second = analyzer.step()
    done = analyzer.step()
    stats = analyzer.close()

    assert first[0] == 0
    assert second[0] == 2
    assert done is None
    assert len(first[2]) == 1
    assert first[3].ball.x is not None
    # max_frames_recorded caps retained stats, but step still returns live frames.
    assert len(stats.frames) == 1
    assert os.path.exists(cfg.output_path)
