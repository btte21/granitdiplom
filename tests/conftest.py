import pytest

from app import InMemoryRepository, create_app


class TestConfig:
    SECRET_KEY = "test-secret-key"
    TESTING = True
    DATABASE_URL = "postgresql://unused"
    APP_PORT = 5005
    DEBUG = False


@pytest.fixture
def repository():
    return InMemoryRepository()


@pytest.fixture
def app(repository):
    app = create_app(TestConfig, repository=repository)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def login_as(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )

