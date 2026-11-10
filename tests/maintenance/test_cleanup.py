"""The cleanup command must preserve user assets and stay inside the project."""
from scripts.maintenance import clean


def write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("keep this content")


def test_cache_discovery_preserves_assets_and_python_environments(tmp_path):
    write(tmp_path / "app/__pycache__/module.pyc")
    write(tmp_path / "tests/__pycache__/test_module.pyc")
    for name in ("models", "data", "artifacts", ".venv", ".git"):
        write(tmp_path / name / "__pycache__/sentinel")
    write(tmp_path / "custom-environment/pyvenv.cfg")
    write(tmp_path / "custom-environment/lib/__pycache__/sentinel")
    assert set(clean.cache_directories(tmp_path)) == {
        tmp_path / "app/__pycache__", tmp_path / "tests/__pycache__"}


def test_cache_discovery_does_not_follow_external_symlinks(tmp_path):
    outside = tmp_path / "outside"
    project = tmp_path / "project"
    write(outside / "sentinel.pyc")
    project.mkdir()
    (project / "__pycache__").symlink_to(outside, target_is_directory=True)
    assert list(clean.cache_directories(project)) == []
    assert (outside / "sentinel.pyc").exists()


def test_preview_is_read_only_and_apply_only_removes_caches(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "app/__pycache__/module.pyc"
    source = tmp_path / "app/module.py"
    notebook_recovery = tmp_path / "notebooks/.ipynb_checkpoints/work.ipynb"
    for path in (cache, source, notebook_recovery):
        write(path)
    monkeypatch.setattr(clean, "ROOT", tmp_path)
    clean.main([])
    assert "Would remove" in capsys.readouterr().out and cache.exists()
    clean.main(["--apply"])
    assert not cache.exists()
    assert source.read_text() == notebook_recovery.read_text() == "keep this content"
