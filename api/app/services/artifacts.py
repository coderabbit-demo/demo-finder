from pathlib import Path

from ..config import settings


def artifact_path(filename: str) -> Path:
    """Locate a generated config artifact in the configured export directory."""
    path = Path(settings.config_export_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path
