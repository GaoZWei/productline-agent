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
