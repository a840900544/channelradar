import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from radar.models import Base


load_dotenv()
url = os.environ.get("RADAR_DATABASE_URL", "sqlite:///data/workbench.sqlite3")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
