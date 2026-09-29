import pytest
from app.services.file_service import FileService


def test_select_file_type_code():
    service = FileService()

    result = service.select_file_type("src/main.py")

    assert result == "code"


def test_select_file_type_documentation():
    service = FileService()

    result = service.select_file_type("docs/readme.md")

    assert result == "documentation"


def test_select_file_type_ignore_node_modules():
    service = FileService()

    result = service.select_file_type("node_modules/package/index.js")

    assert result == "ignore"


def test_chunk_text_splits_text():
    service = FileService()

    chunks = service.chunk_text("abcdefghij", chunk_length=4, redundance=1)

    assert len(chunks) > 1
    assert chunks[0] == "abcd"