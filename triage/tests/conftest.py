"""Shared fixtures for triage tests."""

import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db(tmp_path):
    """Create an in-memory database with triage schema."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Apply base schema
    schema_path = Path(__file__).parent.parent.parent / "schema.sql"
    with open(schema_path) as f:
        conn.executescript(f.read())

    # Apply triage schema
    triage_schema_path = Path(__file__).parent.parent.parent / "triage_schema.sql"
    with open(triage_schema_path) as f:
        conn.executescript(f.read())

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sample_issues():
    """Sample issues for testing."""
    return [
        {
            "id": 1001,
            "number": 100,
            "repo": "micropython/micropython",
            "title": "UART not working on ESP32",
            "body": "When I try to use UART on ESP32-S3, the data is garbled.",
            "author": "user1",
            "state": "open",
            "labels": json.dumps(["port-esp32", "bug"]),
            "created_at": "2025-01-01T00:00:00Z",
            "closed_at": None,
            "updated_at": "2025-01-01T00:00:00Z",
            "comments_count": 3,
        },
        {
            "id": 1002,
            "number": 200,
            "repo": "micropython/micropython",
            "title": "UART baud rate issue on ESP32",
            "body": "UART communication fails at high baud rates on ESP32.",
            "author": "user2",
            "state": "closed",
            "labels": json.dumps(["port-esp32", "bug"]),
            "created_at": "2024-06-01T00:00:00Z",
            "closed_at": "2024-07-01T00:00:00Z",
            "updated_at": "2024-07-01T00:00:00Z",
            "comments_count": 5,
        },
        {
            "id": 1003,
            "number": 300,
            "repo": "micropython/micropython",
            "title": "Add support for I2S on RP2",
            "body": "Feature request: support I2S audio on the RP2 port.",
            "author": "user3",
            "state": "open",
            "labels": json.dumps(["port-rp2", "enhancement"]),
            "created_at": "2025-02-01T00:00:00Z",
            "closed_at": None,
            "updated_at": "2025-02-01T00:00:00Z",
            "comments_count": 1,
        },
    ]


@pytest.fixture
def populated_db(mock_db, sample_issues):
    """Database with sample issues inserted."""
    for issue in sample_issues:
        mock_db.execute(
            """INSERT INTO issues (id, number, repo, title, body, author, state,
               labels, created_at, closed_at, updated_at, comments_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue["id"], issue["number"], issue["repo"], issue["title"],
                issue["body"], issue["author"], issue["state"], issue["labels"],
                issue["created_at"], issue["closed_at"], issue["updated_at"],
                issue["comments_count"],
            ),
        )
    mock_db.commit()
    return mock_db
