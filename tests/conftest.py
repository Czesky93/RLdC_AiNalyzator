"""Pytest configuration for tests."""
import pytest
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base
from database.session import get_db
from web_portal.api.main import app
from fastapi.testclient import TestClient

# Set testing mode
os.environ["TESTING"] = "1"

# Create a single test engine and session factory for all tests
# Use file-based database for testing to avoid in-memory connection issues
TEST_DATABASE_URL = "sqlite:///./test_trading_history.db"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Setup test database once for the session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    # Clean up test database file
    if os.path.exists("test_trading_history.db"):
        os.remove("test_trading_history.db")


@pytest.fixture(autouse=True)
def reset_tables():
    """Reset all tables before each test."""
    # Clear all data
    session = TestSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()
    yield


@pytest.fixture
def db_session():
    """Create a test database session."""
    session = TestSessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client():
    """Create a test client with database override."""
    session = TestSessionLocal()
    
    def override_get_db():
        try:
            yield session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    session.close()
