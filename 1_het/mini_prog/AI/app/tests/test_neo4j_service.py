from unittest.mock import MagicMock, patch
from app.services.neo4j_service import Neo4jService


@patch("app.services.neo4j_service.GraphDatabase.driver")
def test_save_file_runs_query(mock_driver):
    mock_session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = mock_session

    service = Neo4jService()

    service.save_file(
        user_id=1,
        investigation_id=2,
        project_id=3,
        file_path="src/main.py",
        file_name="main.py"
    )

    assert mock_session.run.called


@patch("app.services.neo4j_service.GraphDatabase.driver")
def test_save_function_runs_query(mock_driver):
    mock_session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = mock_session

    service = Neo4jService()

    service.save_function(
        user_id=1,
        investigation_id=2,
        project_id=3,
        file_path="src/main.py",
        function_name="hello",
        start_line=1,
        end_line=5
    )

    assert mock_session.run.called


@patch("app.services.neo4j_service.GraphDatabase.driver")
def test_close_closes_driver(mock_driver):
    service = Neo4jService()

    service.close()

    mock_driver.return_value.close.assert_called_once()