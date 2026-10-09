"""Static metrics through Lizard's Python API (no CLI output parsing).

Lizard provides per function: cyclomatic complexity (McCabe: 1 + decision
points such as if/for/while/case/catch/&&/||/?:), NLOC (lines with code,
comments and blanks excluded), token count, parameter count and start/end
lines. File NLOC and token count also come from Lizard.

Class membership is taken from the Tree-sitter grammar the ingest already uses
(``CodeParser``), because Lizard qualifies names only in some languages
(``UserService::Create`` in C#/Java/C++, plain ``create`` in Python/JS).
"""
import os
import time

from lizard import analyze_file
from lizard_languages import get_reader_for
from tree_sitter import Parser as TSParser

from app.metrics.analyzer import SourceFile
from app.metrics.models import FileMetrics, FunctionMetrics, SkippedFile, StaticAnalysisResult
from app.services.evidence_service import language_for_path, normalize_path
from app.services.file_service import FileService
from app.services.parse_service import CodeParser


def supported_extensions() -> set[str]:
    """The ingest's Tree-sitter languages that Lizard can also read.

    Deriving the set instead of listing it keeps metrics in step with what the
    rest of the pipeline treats as code.
    """
    return {ext for ext in CodeParser.code_parsers if get_reader_for(f"file{ext}")}


def _split_qualified(name: str) -> tuple[str | None, str]:
    parts = [p for p in name.split("::") if p]
    if len(parts) > 1:
        return parts[-2], parts[-1]
    return None, name


def _class_ranges(path: str, source: bytes) -> list[tuple[str, int, int]] | None:
    parser = CodeParser()
    language = parser.select_language(path)
    if language is None:
        return None
    ts_parser = TSParser()
    ts_parser.set_language(language)
    tree = ts_parser.parse(source)
    classes, _ = parser.extract_class_function_nodes(tree.root_node)
    return [
        (parser.get_node_name(node, source) or "", node.start_point[0] + 1, node.end_point[0] + 1)
        for node in classes
    ]


def _enclosing_class(ranges: list[tuple[str, int, int]], line: int) -> str | None:
    """Innermost class-like declaration containing the line."""
    containing = [r for r in ranges if r[0] and r[1] <= line <= r[2]]
    if not containing:
        return None
    return min(containing, key=lambda r: r[2] - r[1])[0]


class LizardAnalyzer:
    name = "lizard"

    def __init__(self):
        self.extensions = supported_extensions()

    def analyze_file(self, file: SourceFile) -> FileMetrics:
        path = normalize_path(file.path)
        code = file.content.decode("utf-8", errors="replace")
        info = analyze_file.analyze_source_code(path, code)

        try:
            ranges = _class_ranges(path, file.content)
        except Exception as e:
            # Class membership is a nice-to-have; the Lizard numbers stand on their own.
            print(f"Tree-sitter class scan failed for {path}: {e}")
            ranges = None

        functions = []
        for fn in info.function_list:
            qualifier, short_name = _split_qualified(fn.name)
            class_name = (_enclosing_class(ranges, fn.start_line) if ranges else None) or qualifier
            functions.append(FunctionMetrics(
                name=short_name,
                longName=fn.long_name,
                className=class_name,
                startLine=fn.start_line,
                endLine=fn.end_line,
                nloc=fn.nloc,
                cyclomaticComplexity=fn.cyclomatic_complexity,
                tokenCount=fn.token_count,
                parameterCount=fn.parameter_count,
                length=fn.length,
            ))

        return FileMetrics(
            path=path,
            language=language_for_path(path),
            nloc=info.nloc,
            tokenCount=info.token_count,
            classCount=len(ranges) if ranges is not None else None,
            functions=functions,
        )

    def analyze(self, files: list[SourceFile]) -> StaticAnalysisResult:
        started = time.perf_counter()
        result = StaticAnalysisResult(analyzer=self.name)
        # Same rule the ingest applies, so metrics cover exactly what the graph and index cover.
        file_types = FileService()

        for file in files:
            path = normalize_path(file.path)
            extension = os.path.splitext(path)[1].lower()

            if file_types.select_file_type(path) == "ignore":
                result.skipped.append(SkippedFile(path=path, reason="ignored_path"))
                continue
            if extension not in self.extensions:
                result.skipped.append(SkippedFile(path=path, reason="unsupported_language"))
                continue
            if not file.content.strip():
                result.skipped.append(SkippedFile(path=path, reason="empty"))
                continue

            try:
                result.files.append(self.analyze_file(file))
            except Exception as e:
                print(f"Lizard analysis failed for {path}: {e}")
                result.skipped.append(SkippedFile(path=path, reason="analyzer_error"))

        result.durationMs = (time.perf_counter() - started) * 1000
        return result
