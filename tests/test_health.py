from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


class FakeSession:
    """Stands in for AsyncSession so these tests don't need a database."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def execute(self, *_args, **_kwargs):
        if self.error:
            raise self.error


def use_session(session: FakeSession) -> None:
    async def override():
        yield session

    app.dependency_overrides[get_session] = override


def test_liveness_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_database_answers(client):
    use_session(FakeSession())

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_503_when_database_down(client):
    use_session(FakeSession(OperationalError("SELECT 1", {}, Exception("connection refused"))))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
