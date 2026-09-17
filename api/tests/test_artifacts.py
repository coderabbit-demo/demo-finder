import pytest

from app.config import settings
from app.services.artifacts import artifact_path


def test_artifact_path_uses_configured_export_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "config_export_dir", str(tmp_path))
    artifact = tmp_path / "generated.coderabbit.yaml"
    artifact.write_text("reviews: {}\n")

    assert artifact_path("generated.coderabbit.yaml") == artifact


def test_artifact_path_rejects_traversal_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "config_export_dir", str(tmp_path))
    artifact = tmp_path / "valid.yaml"
    artifact.write_text("reviews: {}\n")

    # Create a file outside the export directory
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("secret content")

    # Attempt path traversal
    with pytest.raises(FileNotFoundError):
        artifact_path("../secret.txt")

    # Attempt deeper traversal
    with pytest.raises(FileNotFoundError):
        artifact_path("../../etc/passwd")


def test_artifact_path_rejects_absolute_path_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "config_export_dir", str(tmp_path))
    artifact = tmp_path / "valid.yaml"
    artifact.write_text("reviews: {}\n")

    # Attempt absolute path
    with pytest.raises(FileNotFoundError):
        artifact_path("/etc/passwd")

    # Attempt absolute path to another location
    other_path = tmp_path.parent / "other.txt"
    other_path.write_text("other content")
    with pytest.raises(FileNotFoundError):
        artifact_path(str(other_path))
