from pathlib import Path

from ..config import settings


def artifact_path(filename: str) -> Path:
    """Locate a generated config artifact in the configured export directory."""
    root = Path(settings.config_export_dir).resolve()
    candidate = (root / filename).resolve()

    # Ensure the resolved path is contained within the export directory
    try:
        candidate.relative_to(root)
    except ValueError:
        raise FileNotFoundError(filename)

    if not candidate.is_file():
        raise FileNotFoundError(filename)
    return candidate
