"""Shared pytest configuration — requires and enforces the dedicated test database.

Security model
--------------
Integration tests are only allowed to run against ``miconte_test_db``.
Any other database — including the development database ``miconte_db`` — is
rejected at two independent checkpoints before any test can execute:

  1. ``pytest_configure`` (string check, fast):
     Reads ``MICONTE_TEST_DATABASE_URL`` from the process environment (or from
     a local ``.env.test`` file).  Aborts the session immediately if:
     - the variable is absent or empty, OR
     - the URL path does not contain ``/miconte_test_db``.

  2. ``_verify_test_database_identity`` (definitive check, queries PostgreSQL):
     A session-scoped autouse fixture that runs before the first test.
     Calls ``SELECT current_database()`` and aborts the session if the result
     is not ``miconte_test_db``.  This check cannot be bypassed by URL aliases,
     misconfigured hosts, or environment-variable tricks.

No fallback to ``MICONTE_DATABASE_URL`` or to any default derived from it.
If the explicit test-database URL is absent, the session is aborted.

Day-to-day setup
----------------
Create ``<project>/.env.test`` (gitignored) once:

    MICONTE_TEST_DATABASE_URL=postgresql+psycopg://miconte_user:<pwd>@127.0.0.1:5432/miconte_test_db

Or export ``MICONTE_TEST_DATABASE_URL`` in the shell before running pytest.

One-time database creation
--------------------------
    psql -U miconte_user -c "CREATE DATABASE miconte_test_db;"
    MICONTE_DATABASE_URL=...miconte_test_db .venv/bin/alembic upgrade head

After that, ``test_migrations_integration.py`` keeps the schema current via
``downgrade base`` / ``upgrade head`` on every full-suite run.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEST_URL_VAR = "MICONTE_TEST_DATABASE_URL"
_REQUIRED_TEST_DB = "miconte_test_db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_dotenv_test() -> None:
    """Parse ``.env.test`` and inject variables into the process environment.

    Only sets a key if it is NOT already present in ``os.environ`` (shell
    variables always win).  Lines that start with ``#`` or do not contain
    ``=`` are ignored.  No external library required.
    """
    dotenv_path = Path(__file__).parent.parent / ".env.test"
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key not in os.environ:
            os.environ[key] = value


def _clear_sqlalchemy_caches() -> None:
    """Invalidate the LRU caches that SQLAlchemy and settings objects use.

    If any module-level import ran ``get_settings()`` or ``get_engine()``
    before this hook, their cached return values could point to the wrong
    database.  Clearing the caches forces re-evaluation with the new
    ``MICONTE_DATABASE_URL`` value we are about to set.
    """
    try:
        from miconte.core.config import get_settings  # noqa: PLC0415

        get_settings.cache_clear()
    except ImportError:
        pass
    try:
        from miconte.persistence.session import get_engine, get_session_factory  # noqa: PLC0415

        get_engine.cache_clear()
        get_session_factory.cache_clear()
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# pytest hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Validate and enforce the test-database URL before collection begins.

    This hook fires before any test module is imported.  If the validation
    fails, ``pytest.exit()`` is called immediately — no tests run, no
    database connections are opened.
    """
    # Step 0: try to load .env.test so that users can store the URL there.
    _load_dotenv_test()

    # Step 1: require the explicit variable — no fallback to MICONTE_DATABASE_URL.
    test_url = os.environ.get(_TEST_URL_VAR, "").strip()
    if not test_url:
        pytest.exit(
            f"\n\n"
            f"SAFETY ABORT: {_TEST_URL_VAR!r} is not set.\n"
            f"\n"
            f"Integration tests refuse to run without an explicit test-database URL.\n"
            f"Set {_TEST_URL_VAR} to a URL that points to '{_REQUIRED_TEST_DB}'.\n"
            f"\n"
            f"Quick setup (local dev):\n"
            f"  1. Create .env.test at the project root (it is gitignored):\n"
            f"       {_TEST_URL_VAR}=postgresql+psycopg://miconte_user:<pwd>"
            f"@127.0.0.1:5432/{_REQUIRED_TEST_DB}\n"
            f"  2. Run: .venv/bin/pytest\n"
            f"\n"
            f"Or export the variable in your shell before running pytest.\n",
            returncode=3,
        )

    # Step 2: string pre-flight — URL path must contain /miconte_test_db.
    # This is a fast check that rejects obvious misconfigurations (e.g. someone
    # passing the dev URL) before the session fixture opens a real connection.
    if f"/{_REQUIRED_TEST_DB}" not in test_url:
        pytest.exit(
            f"\n\n"
            f"SAFETY ABORT: {_TEST_URL_VAR!r} does not reference '{_REQUIRED_TEST_DB}'.\n"
            f"\n"
            f"Current value path does not contain '/{_REQUIRED_TEST_DB}'.\n"
            f"Refusing to run integration tests against a non-test database.\n",
            returncode=3,
        )

    # Step 3: redirect MICONTE_DATABASE_URL so that get_settings() / get_engine()
    # resolve to the test database for the entire pytest session.
    os.environ["MICONTE_DATABASE_URL"] = test_url

    # Step 4: invalidate any caches already populated by module-level imports.
    _clear_sqlalchemy_caches()


# ---------------------------------------------------------------------------
# Session-scoped autouse fixture — definitive DB identity check
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _verify_test_database_identity() -> Generator[None]:
    """Abort the session if the engine is NOT connected to the authorized test DB.

    This is the definitive validation.  It queries PostgreSQL directly:

        SELECT current_database()

    The result cannot be spoofed by environment variables, connection-string
    manipulation, or URL aliases.  If the engine is connected to any database
    other than ``miconte_test_db``, the session is aborted before the first
    test runs.

    This check complements the string pre-flight in ``pytest_configure``:
    together they form two independent layers of protection.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from miconte.persistence.session import get_engine  # noqa: PLC0415

    engine = get_engine()
    with engine.connect() as conn:
        actual_db: str = conn.execute(text("SELECT current_database()")).scalar_one()

    if actual_db != _REQUIRED_TEST_DB:
        pytest.exit(
            f"\n\n"
            f"SAFETY ABORT: SELECT current_database() returned '{actual_db}'.\n"
            f"\n"
            f"Integration tests must run against '{_REQUIRED_TEST_DB}', "
            f"not '{actual_db}'.\n"
            f"Verify that {_TEST_URL_VAR!r} points to the correct host and "
            f"database name.\n",
            returncode=3,
        )

    yield
