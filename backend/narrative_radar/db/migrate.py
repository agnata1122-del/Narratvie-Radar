from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["db_url"] = db_url
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_to_head(db_url: str) -> None:
    command.upgrade(alembic_config(db_url), "head")
