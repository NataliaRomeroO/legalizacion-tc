"""Tests de helpers de URLs Drive (``file_link``, ``folder_link``)."""

from legalizacion_tc.drive_manager import file_link, folder_link


def test_folder_link() -> None:
    """Verifica folder link."""
    assert folder_link("abc123") == "https://drive.google.com/drive/folders/abc123"


def test_file_link() -> None:
    """Verifica file link."""
    assert file_link("xyz789") == "https://drive.google.com/file/d/xyz789/view"
