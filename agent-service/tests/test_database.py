import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Database
from app.settings import Settings


@pytest.mark.unit
def test_settings_convert_postgresql_url_to_asyncpg() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql://agent:secret@postgres:5432/agent_db",
    )

    assert settings.async_database_url == (
        "postgresql+asyncpg://agent:secret@postgres:5432/agent_db"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_database_builds_lazy_async_session_factory() -> None:
    database = Database("postgresql://agent:secret@postgres:5432/agent_db")

    assert database.engine.dialect.name == "postgresql"
    assert database.session_factory.class_ is AsyncSession

    await database.dispose()
