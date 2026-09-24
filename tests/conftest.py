"""Shared fixtures: a throwaway repo root with a queue/ and assets/."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image


def make_jpeg(path: Path, size: tuple[int, int] = (1080, 1350), color=(40, 40, 48)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=90)
    return path


def render_post_data(post_id: str = "2026-09-25-test", **overrides) -> dict:
    data = {
        "id": post_id,
        "publish_at": "2026-09-25 07:00",
        "approved": False,
        "mode": "render",
        "caption": "שורה ראשונה\nשורה שנייה #סילברפוקס",
        "slides": [
            {"background": "assets/backgrounds/bg.jpg", "title": "בגיל 50.", "accent": "אתה בשיא"},
            {"background": "assets/backgrounds/bg.jpg", "title": "25:", "body": "רק שכחו להגיד לך"},
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Empty repo root containing a valid background photo."""
    make_jpeg(tmp_path / "assets" / "backgrounds" / "bg.jpg", (1200, 1600))
    (tmp_path / "queue").mkdir()
    return tmp_path


def write_post(root: Path, data: dict, dirname: str | None = None) -> Path:
    path = root / "queue" / (dirname or data["id"]) / "post.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
