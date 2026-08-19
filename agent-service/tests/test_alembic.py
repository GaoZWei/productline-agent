from pathlib import Path

import pytest
from alembic.config import Config


@pytest.mark.unit
def test_alembic_configuration_points_to_migrations() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    script_location = config.get_main_option("script_location")

    assert script_location is not None
    assert Path(script_location) == project_root / "migrations"
    assert (project_root / "migrations" / "env.py").is_file()
    assert (project_root / "migrations" / "script.py.mako").is_file()
    assert (project_root / "migrations" / "versions" / "0001_agent_runtime_base.py").is_file()
    assert (project_root / "migrations" / "versions" / "0002_session_context.py").is_file()
    assert (project_root / "migrations" / "versions" / "0003_knowledge_base.py").is_file()
    assert (project_root / "migrations" / "versions" / "0004_embedding_index.py").is_file()
    assert (project_root / "migrations" / "versions" / "0005_keyword_search.py").is_file()
    assert (project_root / "migrations" / "versions" / "0006_vector_search.py").is_file()
