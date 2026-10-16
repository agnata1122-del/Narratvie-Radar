from logging.config import fileConfig

from alembic import context

from narrative_radar.core.config import get_settings
from narrative_radar.db.models import Base
from narrative_radar.db.session import make_engine

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    return config.attributes.get("db_url") or get_settings().database_url


def _configure(**kw: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite는 ALTER가 제한적이라 batch 모드로 생성한다
        user_module_prefix="nr_types.",
        compare_type=True,
        **kw,
    )


def run_migrations_offline() -> None:
    _configure(url=_db_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = make_engine(_db_url())
    with engine.connect() as conn:
        _configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
