"""项目、对话和运行历史的 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agent.state import AgentEvent, RunState
from app.capabilities import ALL_TOOL_NAMES, CapabilitySnapshot, validate_tool_names
from app.skills import LoadedSkill
from app.tools.paths import validate_workspace

SCHEMA_VERSION = 2
ACTIVE_STATUSES = ("queued", "running", "waiting_approval")


class RepositoryError(RuntimeError):
    pass


class NotFoundError(RepositoryError):
    pass


class ConflictError(RepositoryError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        blocked = {
            "authorization",
            "api_key",
            "reasoning",
            "reasoning_content",
            "private_reasoning",
        }
        return {
            key: _safe_payload(item) for key, item in value.items() if key.lower() not in blocked
        }
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    workspace: str
    created_at: str
    updated_at: str
    last_opened_at: str
    available: bool = True


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    project_id: str
    title: str
    created_at: str
    updated_at: str


class SQLiteRepository:
    """短事务、显式外键的单机 repository。"""

    def __init__(self, database_path: Path | str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._db.row_factory = sqlite3.Row
        self._configure()
        self._initialize()

    def _configure(self) -> None:
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")

    def _initialize(self) -> None:
        version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RepositoryError(f"数据库版本 {version} 高于程序支持版本 {SCHEMA_VERSION}")
        if version == SCHEMA_VERSION:
            return
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, workspace TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, termination_reason TEXT, final_answer TEXT,
                    iteration INTEGER NOT NULL DEFAULT 0, modified_files TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run_per_conversation
                ON runs(conversation_id) WHERE status IN ('queued','running','waiting_approval');
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE, role TEXT NOT NULL,
                    content TEXT NOT NULL, sequence INTEGER NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL, UNIQUE(run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    tool_call_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_file_changes (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    path TEXT NOT NULL, old_path TEXT, change_type TEXT NOT NULL,
                    additions INTEGER NOT NULL, deletions INTEGER NOT NULL,
                    before_hash TEXT, after_hash TEXT, before_size INTEGER, after_size INTEGER,
                    diff TEXT, preview TEXT, preview_kind TEXT NOT NULL,
                    UNIQUE(run_id, path)
                );
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
                    required_tools TEXT NOT NULL, recommended_tools TEXT NOT NULL,
                    instructions TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_capabilities (
                    conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
                    enabled_tools TEXT NOT NULL, enabled_skills TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_capability_snapshots (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                    enabled_tools TEXT NOT NULL, skills TEXT NOT NULL,
                    legacy INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._db.execute(
                "INSERT OR IGNORE INTO conversation_capabilities "
                "SELECT id, ?, '[]', ? FROM conversations",
                (json.dumps(sorted(ALL_TOOL_NAMES)), _now()),
            )
            self._db.execute(
                "INSERT OR IGNORE INTO run_capability_snapshots "
                "SELECT id, ?, '[]', 1, created_at FROM runs",
                (json.dumps(sorted(ALL_TOOL_NAMES)),),
            )
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    def register_project(self, workspace: Path | str, name: str | None = None) -> Project:
        path = str(validate_workspace(workspace).resolve())
        timestamp = _now()
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM projects WHERE workspace=?", (path,)).fetchone()
            if row:
                self._db.execute(
                    "UPDATE projects SET last_opened_at=?, updated_at=? WHERE id=?",
                    (timestamp, timestamp, row["id"]),
                )
                return self.get_project(row["id"])
            project_id = str(uuid4())
            title = (name or Path(path).name).strip() or Path(path).name
            self._db.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?)",
                (project_id, title[:120], path, timestamp, timestamp, timestamp),
            )
        return self.get_project(project_id)

    def _project(self, row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            workspace=row["workspace"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_opened_at=row["last_opened_at"],
            available=Path(row["workspace"]).is_dir(),
        )

    def get_project(self, project_id: str, *, touch: bool = False) -> Project:
        with self._lock, self._db:
            row = self._db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise NotFoundError("project not found")
            if touch:
                timestamp = _now()
                self._db.execute(
                    "UPDATE projects SET last_opened_at=?, updated_at=? WHERE id=?",
                    (timestamp, timestamp, project_id),
                )
                row = self._db.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
            assert row is not None
            return self._project(row)

    def list_projects(self) -> list[Project]:
        rows = self._db.execute(
            "SELECT * FROM projects ORDER BY last_opened_at DESC, created_at DESC"
        ).fetchall()
        return [self._project(row) for row in rows]

    def rename_project(self, project_id: str, name: str) -> Project:
        title = name.strip()
        if not title:
            raise ValueError("项目名称不能为空")
        with self._db:
            changed = self._db.execute(
                "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                (title[:120], _now(), project_id),
            ).rowcount
        if not changed:
            raise NotFoundError("project not found")
        return self.get_project(project_id)

    def _has_active_for_project(self, project_id: str) -> bool:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        row = self._db.execute(
            f"SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            f"WHERE c.project_id=? AND r.status IN ({placeholders}) LIMIT 1",
            (project_id, *ACTIVE_STATUSES),
        ).fetchone()
        return row is not None

    def delete_project(self, project_id: str) -> None:
        with self._lock, self._db:
            if self._has_active_for_project(project_id):
                raise ConflictError("项目仍有活动运行")
            changed = self._db.execute("DELETE FROM projects WHERE id=?", (project_id,)).rowcount
            if not changed:
                raise NotFoundError("project not found")

    def create_conversation(self, project_id: str, title: str = "新对话") -> Conversation:
        self.get_project(project_id)
        timestamp = _now()
        conversation_id = str(uuid4())
        with self._db:
            self._db.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?)",
                (
                    conversation_id,
                    project_id,
                    title.strip()[:120] or "新对话",
                    timestamp,
                    timestamp,
                ),
            )
            self._db.execute(
                "INSERT INTO conversation_capabilities VALUES (?,?,?,?)",
                (conversation_id, json.dumps(sorted(ALL_TOOL_NAMES)), "[]", timestamp),
            )
        return self.get_conversation(conversation_id)

    def _conversation(self, row: sqlite3.Row) -> Conversation:
        return Conversation(**dict(row))

    def get_conversation(self, conversation_id: str) -> Conversation:
        row = self._db.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if not row:
            raise NotFoundError("conversation not found")
        return self._conversation(row)

    def list_conversations(self, project_id: str) -> list[Conversation]:
        self.get_project(project_id)
        rows = self._db.execute(
            "SELECT * FROM conversations WHERE project_id=? "
            "ORDER BY updated_at DESC, created_at DESC",
            (project_id,),
        ).fetchall()
        return [self._conversation(row) for row in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        clean = title.strip()
        if not clean:
            raise ValueError("对话标题不能为空")
        with self._db:
            changed = self._db.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (clean[:120], _now(), conversation_id),
            ).rowcount
        if not changed:
            raise NotFoundError("conversation not found")
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._lock, self._db:
            active = self._db.execute(
                f"SELECT 1 FROM runs WHERE conversation_id=? AND status IN ({placeholders})",
                (conversation_id, *ACTIVE_STATUSES),
            ).fetchone()
            if active:
                raise ConflictError("对话仍有活动运行")
            changed = self._db.execute(
                "DELETE FROM conversations WHERE id=?", (conversation_id,)
            ).rowcount
            if not changed:
                raise NotFoundError("conversation not found")

    def create_run(self, conversation_id: str, task: str) -> dict[str, Any]:
        clean = task.strip()
        if not clean:
            raise ValueError("任务不能为空")
        run_id = str(uuid4())
        timestamp = _now()
        with self._lock, self._db:
            conversation = self.get_conversation(conversation_id)
            count = self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conversation_id,)
            ).fetchone()[0]
            try:
                self._db.execute(
                    "INSERT INTO runs(id,conversation_id,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (run_id, conversation_id, "queued", timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("对话已有活动运行") from exc
            self._db.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (str(uuid4()), conversation_id, run_id, "user", clean, count + 1, timestamp),
            )
            snapshot = self._capability_snapshot(conversation_id)
            self._db.execute(
                "INSERT INTO run_capability_snapshots VALUES (?,?,?,?,?)",
                (
                    run_id,
                    json.dumps(snapshot.enabled_tools),
                    json.dumps(list(snapshot.skills), ensure_ascii=False),
                    0,
                    timestamp,
                ),
            )
            existing = self._db.execute(
                "SELECT COUNT(*) FROM runs WHERE conversation_id=?", (conversation_id,)
            ).fetchone()[0]
            title = " ".join(clean.split())[:48]
            self._db.execute(
                "UPDATE conversations SET title=CASE WHEN ?=1 THEN ? ELSE title END, "
                "updated_at=? WHERE id=?",
                (existing, title, timestamp, conversation_id),
            )
            self._db.execute(
                "UPDATE projects SET last_opened_at=?, updated_at=? WHERE id=?",
                (timestamp, timestamp, conversation.project_id),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT r.*, c.project_id, p.workspace FROM runs r "
            "JOIN conversations c ON c.id=r.conversation_id "
            "JOIN projects p ON p.id=c.project_id WHERE r.id=?",
            (run_id,),
        ).fetchone()
        if not row:
            raise NotFoundError("run not found")
        result = dict(row)
        result["modified_files"] = json.loads(result["modified_files"])
        return result

    def list_runs(self, conversation_id: str) -> list[dict[str, Any]]:
        self.get_conversation(conversation_id)
        rows = self._db.execute(
            "SELECT * FROM runs WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["modified_files"] = json.loads(item["modified_files"])
            result.append(item)
        return result

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        self.get_conversation(conversation_id)
        return [
            dict(row)
            for row in self._db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY sequence",
                (conversation_id,),
            ).fetchall()
        ]

    def semantic_messages(
        self, conversation_id: str, *, exclude_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT role,content,run_id FROM messages WHERE conversation_id=?"
        params: list[Any] = [conversation_id]
        if exclude_run_id:
            query += " AND run_id<>?"
            params.append(exclude_run_id)
        query += " AND role IN ('user','assistant') ORDER BY sequence"
        return [dict(row) for row in self._db.execute(query, params).fetchall()]

    def update_run_from_state(self, state: RunState) -> None:
        with self._db:
            self._db.execute(
                "UPDATE runs SET status=?, termination_reason=?, final_answer=?, iteration=?, "
                "modified_files=?, updated_at=? WHERE id=?",
                (
                    state.status.value,
                    state.termination_reason.value if state.termination_reason else None,
                    state.final_answer,
                    state.iteration,
                    json.dumps(sorted(state.modified_files)),
                    _now(),
                    state.run_id,
                ),
            )

    def finish_run(self, state: RunState) -> None:
        with self._lock, self._db:
            self.update_run_from_state(state)
            if state.final_answer is not None:
                count = self._db.execute(
                    "SELECT COUNT(*) FROM messages WHERE conversation_id=?",
                    (state.conversation_id,),
                ).fetchone()[0]
                self._db.execute(
                    "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        state.conversation_id,
                        state.run_id,
                        "assistant",
                        state.final_answer,
                        count + 1,
                        _now(),
                    ),
                )
            self._db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (_now(), state.conversation_id)
            )

    def append_event(self, event: AgentEvent) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO events(run_id,sequence,event_type,timestamp,payload) "
                "VALUES (?,?,?,?,?)",
                (
                    event.session_id,
                    event.sequence,
                    event.event_type,
                    event.timestamp.isoformat(),
                    json.dumps(_safe_payload(dict(event.payload)), ensure_ascii=False),
                ),
            )
            # 每轮保留最近 256 条，避免历史无限增长。
            self._db.execute(
                "DELETE FROM events WHERE run_id=? AND sequence <= "
                "COALESCE((SELECT MAX(sequence)-256 FROM events WHERE run_id=?), -1)",
                (event.session_id, event.session_id),
            )
            payload = _safe_payload(dict(event.payload))
            if event.event_type == "approval.requested" and payload.get("approval_id"):
                self._db.execute(
                    "INSERT OR REPLACE INTO approvals "
                    "(id,run_id,tool_call_id,status,payload,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        payload["approval_id"],
                        event.session_id,
                        payload.get("tool_call_id", ""),
                        "pending",
                        json.dumps(payload, ensure_ascii=False),
                        event.timestamp.isoformat(),
                        event.timestamp.isoformat(),
                    ),
                )
            elif event.event_type == "approval.resolved" and payload.get("approval_id"):
                self._db.execute(
                    "UPDATE approvals SET status=?, updated_at=? WHERE id=? AND run_id=?",
                    (
                        "approved" if payload.get("approved") else "denied",
                        event.timestamp.isoformat(),
                        payload["approval_id"],
                        event.session_id,
                    ),
                )

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        self.get_run(run_id)
        rows = self._db.execute(
            "SELECT sequence,event_type,timestamp,payload FROM events "
            "WHERE run_id=? AND sequence>? ORDER BY sequence",
            (run_id, after),
        ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def save_changes(self, run_id: str, changes: list[dict[str, Any]]) -> None:
        with self._lock, self._db:
            for change in changes:
                values = {"id": str(uuid4()), "run_id": run_id, **change}
                self._db.execute(
                    """INSERT INTO run_file_changes
                    (id,run_id,path,old_path,change_type,additions,deletions,before_hash,after_hash,
                     before_size,after_size,diff,preview,preview_kind)
                    VALUES (:id,:run_id,:path,:old_path,:change_type,:additions,:deletions,
                     :before_hash,:after_hash,:before_size,:after_size,:diff,:preview,:preview_kind)""",
                    values,
                )

    def list_changes(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        return [
            dict(row)
            for row in self._db.execute(
                "SELECT id,path,old_path,change_type,additions,deletions,before_hash,after_hash,"
                "before_size,after_size,preview_kind FROM run_file_changes "
                "WHERE run_id=? ORDER BY path",
                (run_id,),
            ).fetchall()
        ]

    def get_change(self, run_id: str, change_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM run_file_changes WHERE id=? AND run_id=?", (change_id, run_id)
        ).fetchone()
        if not row:
            raise NotFoundError("file change not found")
        return dict(row)

    def recover_interrupted_runs(self) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE runs SET status='failed', termination_reason='server_restarted', "
                "updated_at=? "
                f"WHERE status IN ({placeholders})",
                (_now(), *ACTIVE_STATUSES),
            ).rowcount
            self._db.execute(
                "UPDATE approvals SET status='expired', updated_at=? WHERE status='pending'",
                (_now(),),
            )
        return changed

    def pragmas(self) -> dict[str, Any]:
        return {
            "user_version": self._db.execute("PRAGMA user_version").fetchone()[0],
            "foreign_keys": self._db.execute("PRAGMA foreign_keys").fetchone()[0],
            "journal_mode": self._db.execute("PRAGMA journal_mode").fetchone()[0],
            "busy_timeout": self._db.execute("PRAGMA busy_timeout").fetchone()[0],
        }

    def list_skills(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id,path,name,description,version,digest,required_tools,recommended_tools,"
            "created_at,updated_at FROM skills ORDER BY name"
        ).fetchall()
        return [self._skill_public(row) for row in rows]

    @staticmethod
    def _skill_public(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["required_tools"] = json.loads(item["required_tools"])
        item["recommended_tools"] = json.loads(item["recommended_tools"])
        return item

    def get_skill(self, skill_id: str, *, include_instructions: bool = False) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not row:
            raise NotFoundError("skill not found")
        item = self._skill_public(row)
        if include_instructions:
            item["instructions"] = row["instructions"]
        return item

    def register_skill(self, skill: LoadedSkill) -> dict[str, Any]:
        timestamp = _now()
        with self._lock, self._db:
            row = self._db.execute("SELECT id FROM skills WHERE path=?", (skill.path,)).fetchone()
            skill_id = row["id"] if row else str(uuid4())
            try:
                self._db.execute(
                    "INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET name=excluded.name,"
                    "description=excluded.description,"
                    "version=excluded.version,digest=excluded.digest,required_tools=excluded.required_tools,"
                    "recommended_tools=excluded.recommended_tools,instructions=excluded.instructions,updated_at=excluded.updated_at",
                    (
                        skill_id,
                        skill.path,
                        skill.name,
                        skill.description,
                        skill.version,
                        skill.digest,
                        json.dumps(skill.required_tools),
                        json.dumps(skill.recommended_tools),
                        skill.instructions,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("Skill 名称已经存在") from exc
        return self.get_skill(skill_id, include_instructions=True)

    def delete_skill(self, skill_id: str) -> None:
        with self._lock, self._db:
            for row in self._db.execute(
                "SELECT enabled_skills FROM conversation_capabilities"
            ).fetchall():
                if skill_id in json.loads(row["enabled_skills"]):
                    raise ConflictError("Skill 仍被对话启用")
            changed = self._db.execute("DELETE FROM skills WHERE id=?", (skill_id,)).rowcount
            if not changed:
                raise NotFoundError("skill not found")

    def _capability_snapshot(self, conversation_id: str) -> CapabilitySnapshot:
        self.get_conversation(conversation_id)
        row = self._db.execute(
            "SELECT * FROM conversation_capabilities WHERE conversation_id=?", (conversation_id,)
        ).fetchone()
        if not row:
            return CapabilitySnapshot(tuple(sorted(ALL_TOOL_NAMES)))
        enabled_tools = validate_tool_names(json.loads(row["enabled_tools"]))
        skills = []
        for skill_id in json.loads(row["enabled_skills"]):
            skill = self.get_skill(skill_id, include_instructions=True)
            skills.append(
                {
                    key: skill[key]
                    for key in ("id", "name", "version", "digest", "required_tools", "instructions")
                }
            )
        return CapabilitySnapshot(enabled_tools, tuple(skills))

    def get_conversation_capabilities(self, conversation_id: str) -> dict[str, Any]:
        snapshot = self._capability_snapshot(conversation_id)
        return {**snapshot.public_dict(), "conversation_id": conversation_id}

    def set_conversation_capabilities(
        self, conversation_id: str, enabled_tools: list[str], enabled_skills: list[str]
    ) -> dict[str, Any]:
        tools = validate_tool_names(enabled_tools)
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._lock, self._db:
            self.get_conversation(conversation_id)
            active = self._db.execute(
                f"SELECT 1 FROM runs WHERE conversation_id=? AND status IN ({placeholders})",
                (conversation_id, *ACTIVE_STATUSES),
            ).fetchone()
            if active:
                raise ConflictError("运行期间不能修改能力配置")
            selected: list[str] = []
            for skill_id in dict.fromkeys(enabled_skills):
                skill = self.get_skill(skill_id)
                missing = sorted(set(skill["required_tools"]) - set(tools))
                if missing:
                    raise ValueError(f"Skill {skill['name']} 缺少必需工具: {', '.join(missing)}")
                selected.append(skill_id)
            self._db.execute(
                "INSERT INTO conversation_capabilities VALUES (?,?,?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET enabled_tools=excluded.enabled_tools,"
                "enabled_skills=excluded.enabled_skills,updated_at=excluded.updated_at",
                (conversation_id, json.dumps(tools), json.dumps(selected), _now()),
            )
        return self.get_conversation_capabilities(conversation_id)

    def get_run_capabilities(
        self, run_id: str, *, include_instructions: bool = False
    ) -> CapabilitySnapshot:
        self.get_run(run_id)
        row = self._db.execute(
            "SELECT * FROM run_capability_snapshots WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            return CapabilitySnapshot(tuple(sorted(ALL_TOOL_NAMES)), legacy=True)
        skills = json.loads(row["skills"])
        if not include_instructions:
            skills = [
                {key: value for key, value in skill.items() if key != "instructions"}
                for skill in skills
            ]
        return CapabilitySnapshot(
            tuple(json.loads(row["enabled_tools"])), tuple(skills), bool(row["legacy"])
        )


def public_dict(value: Project | Conversation) -> dict[str, Any]:
    return asdict(value)
