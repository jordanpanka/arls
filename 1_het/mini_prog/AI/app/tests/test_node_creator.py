from app.services.node_creator import NodeCreator


def test_split_code_semantically_returns_one_chunk_for_short_code():
    creator = NodeCreator()

    chunks = creator.split_code_semantically("def hello():\n    return 1")

    assert len(chunks) == 1


def test_split_code_by_lines_creates_multiple_chunks():
    creator = NodeCreator()

    code = "line1\nline2\nline3\nline4\n"

    chunks = creator.split_code_by_lines(code, max_chars=10, overlap=2)

    assert len(chunks) > 1