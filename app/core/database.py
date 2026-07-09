from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings

# pool_pre_ping avoids stale-connection errors after Postgres restarts/idles,
# which matters on a small single-box VPS deployment.
engine = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session per request."""
    with Session(engine) as session:
        yield session
