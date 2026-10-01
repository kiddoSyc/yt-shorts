import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    """Isolated settings: temp data dir, ignores the real .env file."""
    return Settings(_env_file=None, data_dir=tmp_path / "data", log_dir=tmp_path / "logs",
                    whisper_model_size="tiny", max_video_height=480)
