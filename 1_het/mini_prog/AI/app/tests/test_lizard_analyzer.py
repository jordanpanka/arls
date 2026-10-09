from lizard_languages import get_reader_for

from app.metrics.analyzer import SourceFile
from app.metrics.lizard_analyzer import LizardAnalyzer, supported_extensions
from app.services.file_service import FileService
from app.services.parse_service import CodeParser

CSHARP = b"""namespace App {
    public class UserService {
        public int Create(int age, string name, bool admin) {
            if (age > 18 && name != null) {
                return 1;
            }
            for (int i = 0; i < age; i++) { }
            return 0;
        }

        public void Ping() { }
    }
}
"""

PYTHON = b"""class Repo:
    def find(self, key, default=None):
        if key:
            return 1
        return default


def helper():
    pass
"""


def analyze(path, content):
    result = LizardAnalyzer().analyze([SourceFile(path=path, content=content)])
    assert not result.skipped
    return result.files[0]


def test_function_metrics_are_mapped_from_lizard():
    file = analyze("src/UserService.cs", CSHARP)

    create = next(f for f in file.functions if f.name == "Create")
    # 1 + if + && + for
    assert create.cyclomaticComplexity == 4
    assert create.parameterCount == 3
    assert create.className == "UserService"
    assert create.startLine == 3
    assert create.endLine == 9
    assert create.length == 7
    assert create.nloc > 0 and create.tokenCount > 0
    assert "Create" in create.longName

    ping = next(f for f in file.functions if f.name == "Ping")
    assert ping.cyclomaticComplexity == 1
    assert ping.parameterCount == 0


def test_file_metrics_include_language_size_and_classes():
    file = analyze("src\\UserService.cs", CSHARP)

    assert file.path == "src/UserService.cs"
    assert file.language == "csharp"
    assert file.classCount == 1
    assert len(file.functions) == 2
    assert file.nloc > 0


def test_python_methods_get_class_name_from_tree_sitter():
    file = analyze("app/repo.py", PYTHON)

    find = next(f for f in file.functions if f.name == "find")
    helper = next(f for f in file.functions if f.name == "helper")

    assert find.className == "Repo"
    assert helper.className is None
    assert find.cyclomaticComplexity == 2
    # Lizard counts self like any other parameter.
    assert find.parameterCount == 3


def test_unsupported_and_empty_files_are_skipped_with_reason():
    result = LizardAnalyzer().analyze([
        SourceFile(path="README.md", content=b"# hello"),
        SourceFile(path="src/empty.py", content=b"   \n"),
        SourceFile(path="web/node_modules/lib/index.js", content=b"function f() {}"),
    ])

    assert result.files == []
    assert {(s.path, s.reason) for s in result.skipped} == {
        ("README.md", "unsupported_language"),
        ("src/empty.py", "empty"),
        ("web/node_modules/lib/index.js", "ignored_path"),
    }


def test_file_without_functions_still_has_file_metrics():
    file = analyze("src/constants.py", b"A = 1\nB = 2\n")

    assert file.functions == []
    assert file.nloc == 2


def test_code_extensions_are_in_sync_across_ingest_tree_sitter_and_lizard():
    # Ingest and metrics share one definition of "code"; Lizard must read all of it.
    assert set(FileService.code_sources) == set(CodeParser.code_parsers)
    assert supported_extensions() == set(CodeParser.code_parsers)
    for extension in CodeParser.code_parsers:
        assert get_reader_for(f"file{extension}") is not None, extension
