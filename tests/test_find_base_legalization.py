"""Tests de ``find_base_legalization_file``: prioridad legacy manual vs versionado."""

from legalizacion_tc.drive_manager import DriveFile, find_base_legalization_file


def _file(name: str, file_id: str, modified_time: float = 0.0) -> DriveFile:
    """Helper de prueba: file."""
    return DriveFile(
        file_id=file_id,
        name=name,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        modified_time=modified_time,
    )


def test_find_base_prefers_manual_legacy_over_versioned():
    """Verifica find base prefers manual legacy over versioned."""
    files = [
        _file("Formato de Legalización TC 1111 - 3 - JULIO - 2026.xlsx", "julio", 10.0),
        _file("Formato de Legalización TC 1111 - MAYO- 2026.xlsx", "mayo-manual", 1.0),
        _file("Formato de Legalización TC 1111 - MAYO - 2026.xlsx", "mayo-gen", 5.0),
    ]
    base = find_base_legalization_file(files, "1111")
    assert base is not None
    assert base.file_id == "mayo-manual"


def test_find_base_prefers_most_recent_versioned():
    """Verifica find base prefers most recent versioned."""
    files = [
        _file("Formato de Legalización TC 1111 - 2 - JULIO - 2026.xlsx", "v1", 2.0),
        _file("Formato de Legalización TC 1111 - 2 - JULIO v2 - 2026.xlsx", "v2", 3.0),
        _file("Formato de Legalización TC 1111 - MAYO - 2026.xlsx", "legacy", 1.0),
    ]
    base = find_base_legalization_file(files, "1111")
    assert base is not None
    assert base.file_id == "v2"


def test_find_base_excludes_output_name():
    """Verifica find base excludes output name."""
    files = [
        _file("Formato de Legalización TC 1111 - 3 - JULIO - 2026.xlsx", "julio", 10.0),
        _file("Formato de Legalización TC 1111 - MAYO- 2026.xlsx", "mayo", 1.0),
    ]
    base = find_base_legalization_file(
        files,
        "1111",
        exclude_name="Formato de Legalización TC 1111 - MAYO- 2026.xlsx",
    )
    assert base is not None
    assert base.file_id == "julio"


def test_find_base_returns_none_when_empty():
    """Verifica find base returns none when empty."""
    assert find_base_legalization_file([], "1111") is None
