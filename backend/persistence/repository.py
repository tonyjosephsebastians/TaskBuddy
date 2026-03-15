from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.config import (
    DATA_DIR,
    DATABASE_PATH,
    DEFAULT_DEMO_USERS,
    MAX_ADMIN_USERS,
    MAX_TASK_FLOWS_PER_THREAD,
    MAX_THREADS_PER_USER,
    MAX_STANDARD_USERS,
    SUPPORTED_ROLES,
    THREAD_TITLE_LIMIT,
)
from backend.errors import AppError
from backend.models import ThreadDetail, ThreadSummary, TraceStep, TurnExecution, UserAccount
from backend.safety.guard import mask_sensitive_numbers, mask_sensitive_payload
from backend.security import hash_password


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_thread_title(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= THREAD_TITLE_LIMIT:
        return normalized
    return f"{normalized[: THREAD_TITLE_LIMIT - 1].rstrip()}..."


PASSWORD_UPPERCASE_PATTERN = re.compile(r"[A-Z]")
PASSWORD_NUMBER_PATTERN = re.compile(r"\d")


def validate_password_policy(password: str) -> None:
    if len(password) < 6:
        raise AppError("INVALID_PASSWORD", "Password must be at least 6 characters.", 422)
    if PASSWORD_UPPERCASE_PATTERN.search(password) is None:
        raise AppError("INVALID_PASSWORD", "Password must include at least 1 uppercase letter.", 422)
    if PASSWORD_NUMBER_PATTERN.search(password) is None:
        raise AppError("INVALID_PASSWORD", "Password must include at least 1 number.", 422)


class TaskRepository:
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            self._migrate_legacy_schema(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS task_turns (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    raw_input TEXT NOT NULL,
                    sanitized_input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_output TEXT NOT NULL,
                    output_data_json TEXT NOT NULL,
                    tools_used_json TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES threads(id)
                );

                CREATE TABLE IF NOT EXISTS execution_steps (
                    id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    tool_name TEXT,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(turn_id) REFERENCES task_turns(id)
                );

                CREATE INDEX IF NOT EXISTS idx_threads_user_updated
                ON threads (user_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_task_turns_thread_created
                ON task_turns (thread_id, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_execution_steps_turn_step
                ON execution_steps (turn_id, step_number ASC);
                """
            )
            self._ensure_default_users(connection)
            connection.commit()

    def get_user_by_username(self, username: str) -> UserAccount | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?)",
                (username,),
            ).fetchone()
            return self._build_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> UserAccount | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._build_user(row) if row else None

    def list_users(self) -> list[UserAccount]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
            return [self._build_user(row) for row in rows]

    def create_user(self, username: str, password: str, role: str) -> UserAccount:
        username = username.strip()
        role = role.strip().lower()

        if len(username) < 3:
            raise AppError("INVALID_USERNAME", "Username must be at least 3 characters.", 422)
        validate_password_policy(password)
        if role not in SUPPORTED_ROLES:
            raise AppError("INVALID_ROLE", "Role must be admin or user.", 422)
        if self.get_user_by_username(username):
            raise AppError("USERNAME_EXISTS", "Username already exists.", 409)

        user_id = str(uuid4())
        created_at = utc_now()
        password_hash, password_salt = hash_password(password)
        with self.connect() as connection:
            self._ensure_role_capacity(connection, role)
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, password_salt, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, password_salt, role, created_at),
            )
            connection.commit()
        return UserAccount(
            user_id=user_id,
            username=username,
            role=role,
            created_at=created_at,
            password_hash=password_hash,
            password_salt=password_salt,
        )

    def delete_user(self, user_id: str) -> bool:
        with self.connect() as connection:
            user = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                return False

            if user["role"] == "admin":
                admin_count = connection.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'admin'").fetchone()["count"]
                if admin_count <= 1:
                    raise AppError("LAST_ADMIN", "TaskBuddy must keep at least one admin user.", 422)

            thread_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM threads WHERE user_id = ?", (user_id,)).fetchall()
            ]
            if thread_ids:
                turn_ids = [
                    row["id"]
                    for thread_id in thread_ids
                    for row in connection.execute("SELECT id FROM task_turns WHERE thread_id = ?", (thread_id,)).fetchall()
                ]
                if turn_ids:
                    connection.executemany(
                        "DELETE FROM execution_steps WHERE turn_id = ?",
                        [(turn_id,) for turn_id in turn_ids],
                    )
                connection.executemany(
                    "DELETE FROM task_turns WHERE thread_id = ?",
                    [(thread_id,) for thread_id in thread_ids],
                )
                connection.executemany(
                    "DELETE FROM threads WHERE id = ?",
                    [(thread_id,) for thread_id in thread_ids],
                )

            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            connection.commit()
            return True

    def create_thread(self, user_id: str) -> ThreadDetail:
        thread_id = str(uuid4())
        created_at = utc_now()
        with self.connect() as connection:
            self._ensure_thread_capacity(connection, user_id)
            connection.execute(
                """
                INSERT INTO threads (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, user_id, "New chat", created_at, created_at),
            )
            connection.commit()
        return ThreadDetail(thread_id=thread_id, title="New chat", created_at=created_at, updated_at=created_at, turns=[])

    def list_threads(self, user_id: str, search: str = "") -> list[ThreadSummary]:
        term = f"%{search.lower()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    threads.id,
                    threads.title,
                    threads.updated_at,
                    COALESCE((
                        SELECT raw_input
                        FROM task_turns
                        WHERE task_turns.thread_id = threads.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ), '') AS last_message_preview
                FROM threads
                WHERE threads.user_id = ?
                  AND (
                    ? = ''
                    OR lower(threads.title) LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM task_turns
                        WHERE task_turns.thread_id = threads.id
                          AND lower(task_turns.raw_input) LIKE ?
                    )
                  )
                ORDER BY threads.updated_at DESC
                """,
                (user_id, search, term, term),
            ).fetchall()
            return [
                ThreadSummary(
                    thread_id=row["id"],
                    title=row["title"],
                    last_message_preview=row["last_message_preview"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    def get_thread(self, thread_id: str, user_id: str) -> ThreadDetail | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return self._build_thread_detail(connection, row)

    def save_turn(self, thread_id: str, user_id: str, execution: TurnExecution) -> TurnExecution:
        with self.connect() as connection:
            thread = connection.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()
            if thread is None:
                raise AppError("THREAD_NOT_FOUND", "Thread not found.", 404, {"thread_id": thread_id})

            turn_count = connection.execute(
                "SELECT COUNT(*) AS count FROM task_turns WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()["count"]
            if turn_count >= MAX_TASK_FLOWS_PER_THREAD:
                raise AppError(
                    "THREAD_FLOW_LIMIT_REACHED",
                    f"Each chat supports up to {MAX_TASK_FLOWS_PER_THREAD} task flows.",
                    422,
                    {"thread_id": thread_id, "max": MAX_TASK_FLOWS_PER_THREAD},
                )

            connection.execute(
                """
                INSERT INTO task_turns (
                    id, thread_id, raw_input, sanitized_input, status, final_output,
                    output_data_json, tools_used_json, trace_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution.turn_id,
                    thread_id,
                    mask_sensitive_numbers(execution.task_text),
                    mask_sensitive_numbers(execution.sanitized_text),
                    execution.status,
                    mask_sensitive_numbers(execution.final_output),
                    json.dumps(mask_sensitive_payload(execution.output_data)),
                    json.dumps(execution.tools_used),
                    execution.trace_id,
                    execution.timestamp,
                ),
            )
            for step in execution.execution_steps:
                connection.execute(
                    """
                    INSERT INTO execution_steps (
                        id, turn_id, step_number, phase, tool_name, status,
                        message, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{execution.turn_id}-{step.step_number}",
                        execution.turn_id,
                        step.step_number,
                        step.phase,
                        step.tool_name,
                        step.status,
                        mask_sensitive_numbers(step.message),
                        json.dumps(mask_sensitive_payload(step.payload or {})),
                        execution.timestamp,
                    ),
                )

            new_title = thread["title"]
            if turn_count == 0 and thread["title"] == "New chat":
                new_title = make_thread_title(execution.sanitized_text)

            connection.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                (new_title, execution.timestamp, thread_id),
            )
            connection.commit()
        return execution

    def delete_thread(self, thread_id: str, user_id: str) -> bool:
        with self.connect() as connection:
            thread = connection.execute(
                "SELECT id FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()
            if thread is None:
                return False

            turn_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM task_turns WHERE thread_id = ?",
                    (thread_id,),
                ).fetchall()
            ]
            if turn_ids:
                connection.executemany(
                    "DELETE FROM execution_steps WHERE turn_id = ?",
                    [(turn_id,) for turn_id in turn_ids],
                )

            connection.execute("DELETE FROM task_turns WHERE thread_id = ?", (thread_id,))
            connection.execute("DELETE FROM threads WHERE id = ? AND user_id = ?", (thread_id, user_id))
            connection.commit()
            return True

    def get_thread_turn_count(self, thread_id: str, user_id: str) -> int:
        with self.connect() as connection:
            thread = connection.execute(
                "SELECT id FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            ).fetchone()
            if thread is None:
                raise AppError("THREAD_NOT_FOUND", "Thread not found.", 404, {"thread_id": thread_id})
            return connection.execute(
                "SELECT COUNT(*) AS count FROM task_turns WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()["count"]

    def ensure_thread_flow_capacity(self, thread_id: str, user_id: str) -> None:
        turn_count = self.get_thread_turn_count(thread_id, user_id)
        if turn_count >= MAX_TASK_FLOWS_PER_THREAD:
            raise AppError(
                "THREAD_FLOW_LIMIT_REACHED",
                f"Each chat supports up to {MAX_TASK_FLOWS_PER_THREAD} task flows.",
                422,
                {"thread_id": thread_id, "max": MAX_TASK_FLOWS_PER_THREAD},
            )

    def get_thread_count(self, user_id: str) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) AS count FROM threads WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]

    def _build_thread_detail(self, connection: sqlite3.Connection, row: sqlite3.Row) -> ThreadDetail:
        turn_rows = connection.execute(
            "SELECT * FROM task_turns WHERE thread_id = ? ORDER BY created_at ASC",
            (row["id"],),
        ).fetchall()
        turns = [self._build_turn(connection, turn_row) for turn_row in turn_rows]
        return ThreadDetail(
            thread_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            turns=turns,
        )

    def _build_turn(self, connection: sqlite3.Connection, row: sqlite3.Row) -> TurnExecution:
        steps = connection.execute(
            "SELECT * FROM execution_steps WHERE turn_id = ? ORDER BY step_number ASC",
            (row["id"],),
        ).fetchall()
        execution_steps = [
            TraceStep(
                step_number=step["step_number"],
                phase=step["phase"],
                status=step["status"],
                message=step["message"],
                tool_name=step["tool_name"],
                payload=json.loads(step["payload_json"] or "{}"),
            )
            for step in steps
        ]
        return TurnExecution(
            turn_id=row["id"],
            task_text=row["raw_input"],
            sanitized_text=row["sanitized_input"],
            status=row["status"],
            final_output=row["final_output"],
            output_data=json.loads(row["output_data_json"]),
            tools_used=json.loads(row["tools_used_json"]),
            execution_steps=execution_steps,
            timestamp=row["created_at"],
            trace_id=row["trace_id"],
        )

    def _build_user(self, row: sqlite3.Row) -> UserAccount:
        return UserAccount(
            user_id=row["id"],
            username=row["username"],
            role=row["role"],
            created_at=row["created_at"],
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
        )

    def _ensure_role_capacity(self, connection: sqlite3.Connection, role: str) -> None:
        if role == "admin":
            max_users = MAX_ADMIN_USERS
            message = f"TaskBuddy supports only {MAX_ADMIN_USERS} admin account."
        else:
            max_users = MAX_STANDARD_USERS
            message = f"TaskBuddy supports up to {MAX_STANDARD_USERS} standard user accounts."

        current_count = connection.execute(
            "SELECT COUNT(*) AS count FROM users WHERE role = ?",
            (role,),
        ).fetchone()["count"]
        if current_count >= max_users:
            raise AppError(
                "ROLE_LIMIT_REACHED",
                message,
                422,
                {"role": role, "max": max_users},
            )

    def _ensure_thread_capacity(self, connection: sqlite3.Connection, user_id: str) -> None:
        current_count = connection.execute(
            "SELECT COUNT(*) AS count FROM threads WHERE user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        if current_count >= MAX_THREADS_PER_USER:
            raise AppError(
                "THREAD_LIMIT_REACHED",
                f"TaskBuddy supports up to {MAX_THREADS_PER_USER} chat threads per user.",
                422,
                {"user_id": user_id, "max": MAX_THREADS_PER_USER},
            )

    def _ensure_default_users(self, connection: sqlite3.Connection) -> None:
        for user in DEFAULT_DEMO_USERS:
            row = connection.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?)",
                (user["username"],),
            ).fetchone()
            if row:
                continue
            password_hash, password_salt = hash_password(user["password"])
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, password_salt, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), user["username"], password_hash, password_salt, user["role"], utc_now()),
            )

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "execution_steps" in tables:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(execution_steps)").fetchall()
            }
            if "turn_id" not in columns:
                connection.execute("DROP TABLE execution_steps")
        if "task_runs" in tables:
            connection.execute("DROP TABLE task_runs")
