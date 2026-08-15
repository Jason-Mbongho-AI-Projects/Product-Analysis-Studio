"""Shared fixtures. Every test runs against an isolated temporary database."""

from __future__ import annotations

import pytest

from pas.config import AppConfig
from pas.storage import db as db_module
from pas.storage import repositories as repo


@pytest.fixture
def conn(tmp_path):
    db_module.reset_thread_state()
    connection = db_module.get_connection(tmp_path / "test.sqlite3")
    db_module.migrate(connection)
    yield connection
    db_module.reset_thread_state()


@pytest.fixture
def workspace(conn):
    return repo.ensure_default_workspace(conn)


@pytest.fixture
def product(conn, workspace):
    return repo.create_product(
        conn,
        workspace_id=workspace,
        name="Test Product",
        intake_kind="idea",
        intake_input="An AI assistant for hospital cybersecurity compliance",
        category="Healthcare AI",
    )


@pytest.fixture
def analysis(conn, workspace, product):
    return repo.create_analysis(conn, workspace_id=workspace, product_id=product)["id"]


@pytest.fixture
def config(tmp_path):
    return AppConfig(api_key="test-key", db_path=tmp_path / "test.sqlite3")
