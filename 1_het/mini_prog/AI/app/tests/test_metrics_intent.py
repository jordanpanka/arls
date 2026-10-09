import pytest

from app.metrics.intent import detect_metrics_intent


@pytest.mark.parametrize("question", [
    "What does getUserName() return?",
    "Where is the authentication handled?",
    "How do I install the project?",
    "Explain the upload endpoint",
])
def test_plain_code_questions_do_not_use_metrics(question):
    assert detect_metrics_intent(question).use_metrics is False


@pytest.mark.parametrize("question, focus", [
    ("Which files are the most complex?", "complexity"),
    ("Which functions have the highest cyclomatic complexity?", "complexity"),
    ("Which components have the highest fan-out?", "dependency"),
    ("Which classes have the most dependencies?", "dependency"),
    ("Which files contain unusually long functions?", "maintainability"),
    ("Which files should I investigate for possible refactoring?", "maintainability"),
    ("Where are the maintenance hotspots?", "maintainability"),
    ("Show me the main architectural hotspots.", "dependency"),
])
def test_ranking_questions_use_repository_scope(question, focus):
    intent = detect_metrics_intent(question)

    assert intent.use_metrics is True
    assert intent.scope == "repository"
    assert intent.focus == focus


def test_question_about_one_component_uses_entity_scope():
    intent = detect_metrics_intent("Why is UserService difficult to maintain?")

    assert intent.use_metrics is True
    assert intent.scope == "entity"
    assert intent.focus == "maintainability"
