from app.config import settings
from app.services.artifacts import artifact_path


def test_artifact_path_uses_configured_export_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "config_export_dir", str(tmp_path))
    artifact = tmp_path / "generated.coderabbit.yaml"
    artifact.write_text("reviews: {}\n")

    assert artifact_path("generated.coderabbit.yaml") == artifact
