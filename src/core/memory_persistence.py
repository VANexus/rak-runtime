"""
持久化记忆后端

将认知记忆系统从纯内存升级为持久化存储：
- 短期记忆：JSON 文件（可升级为 Redis）
- 长期记忆：SQLite（可升级为 PostgreSQL）
- 执行日志：追加写入文件（可升级为 InfluxDB）

设计原则：
- 无外部依赖：纯 Python 标准库
- 渐进升级：先文件，后数据库
- 重启恢复：程序重启后记忆不丢失
"""

import json
import logging
import os
import sqlite3
import time
from typing import List, Dict, Optional, Any
from dataclasses import asdict

logger = logging.getLogger(__name__)


class FileMemoryBackend:
    """
    文件持久化后端（短期记忆 + 执行日志）。

    存储格式：
    - short_term.json: 短期记忆
    - execution_log.jsonl: 执行日志（追加写入）
    - reflection_log.jsonl: 反思日志
    """

    def __init__(self, data_dir: str = "data/memory"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.short_term_path = os.path.join(data_dir, "short_term.json")
        self.execution_log_path = os.path.join(data_dir, "execution_log.jsonl")
        self.reflection_log_path = os.path.join(data_dir, "reflection_log.jsonl")

    def save_short_term_memories(self, memories: List[Dict]):
        """保存短期记忆"""
        try:
            with open(self.short_term_path, "w") as f:
                json.dump(memories, f, ensure_ascii=False, indent=2)
            logger.debug(f"[FileBackend] 保存 {len(memories)} 条短期记忆")
        except Exception as e:
            logger.warning(f"[FileBackend] 保存短期记忆失败: {e}")

    def load_short_term_memories(self) -> List[Dict]:
        """加载短期记忆"""
        if not os.path.exists(self.short_term_path):
            return []
        try:
            with open(self.short_term_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[FileBackend] 加载短期记忆失败: {e}")
            return []

    def append_execution_log(self, entry: Dict):
        """追加执行日志"""
        try:
            with open(self.execution_log_path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[FileBackend] 写入执行日志失败: {e}")

    def read_execution_log(self, last_n: int = 100) -> List[Dict]:
        """读取最近 N 条执行日志"""
        if not os.path.exists(self.execution_log_path):
            return []
        try:
            with open(self.execution_log_path) as f:
                lines = f.readlines()
            entries = []
            for line in lines[-last_n:]:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
            return entries
        except Exception as e:
            logger.warning(f"[FileBackend] 读取执行日志失败: {e}")
            return []

    def append_reflection(self, entry: Dict):
        """追加反思日志"""
        try:
            with open(self.reflection_log_path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[FileBackend] 写入反思日志失败: {e}")


class SQLiteMemoryBackend:
    """
    SQLite 持久化后端（长期记忆）。

    表结构：
    - memories: 长期记忆条目
    - embeddings: 向量存储
    - execution_stats: 执行统计
    """

    def __init__(self, db_path: str = "data/memory/long_term.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    metadata TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    decay_rate REAL DEFAULT 0.01
                );

                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
                CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);

                CREATE TABLE IF NOT EXISTS embeddings (
                    memory_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS execution_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    latency_ms REAL,
                    timestamp REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_exec_action ON execution_stats(action);
                CREATE INDEX IF NOT EXISTS idx_exec_time ON execution_stats(timestamp DESC);
            """)
            conn.commit()
            logger.info(f"[SQLiteBackend] 数据库初始化完成: {self.db_path}")
        finally:
            conn.close()

    def save_memory(self, entry: Dict, embedding: Optional[List[float]] = None):
        """保存记忆条目"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO memories
                (id, content, memory_type, layer, importance, metadata,
                 created_at, last_accessed, access_count, decay_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry["id"],
                entry["content"],
                entry["memory_type"],
                entry.get("layer", "long_term"),
                entry.get("importance", 0.5),
                json.dumps(entry.get("metadata", {}), ensure_ascii=False),
                entry.get("created_at", time.time()),
                entry.get("last_accessed", time.time()),
                entry.get("access_count", 0),
                entry.get("decay_rate", 0.01),
            ))

            # 保存向量
            if embedding:
                import struct
                vec_bytes = struct.pack(f"{len(embedding)}f", *embedding)
                conn.execute("""
                    INSERT OR REPLACE INTO embeddings
                    (memory_id, vector, dimension)
                    VALUES (?, ?, ?)
                """, (entry["id"], vec_bytes, len(embedding)))

            conn.commit()
        finally:
            conn.close()

    def load_all_memories(self) -> List[Dict]:
        """加载所有记忆"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT * FROM memories ORDER BY importance DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def load_embeddings(self) -> Dict[str, List[float]]:
        """加载所有向量"""
        import struct
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT memory_id, vector, dimension FROM embeddings")
            result = {}
            for row in cursor:
                memory_id, vec_bytes, dim = row
                vec = struct.unpack(f"{dim}f", vec_bytes)
                result[memory_id] = list(vec)
            return result
        finally:
            conn.close()

    def search_by_type(self, memory_type: str, limit: int = 10) -> List[Dict]:
        """按类型搜索记忆"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("""
                SELECT * FROM memories
                WHERE memory_type = ?
                ORDER BY importance DESC, last_accessed DESC
                LIMIT ?
            """, (memory_type, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_by_content(self, keywords: List[str], limit: int = 10) -> List[Dict]:
        """按关键词搜索记忆"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conditions = " OR ".join(["content LIKE ?"] * len(keywords))
            params = [f"%{kw}%" for kw in keywords]
            params.append(limit)

            cursor = conn.execute(f"""
                SELECT * FROM memories
                WHERE {conditions}
                ORDER BY importance DESC
                LIMIT ?
            """, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_access(self, memory_id: str):
        """更新访问信息"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                UPDATE memories
                SET last_accessed = ?, access_count = access_count + 1
                WHERE id = ?
            """, (time.time(), memory_id))
            conn.commit()
        finally:
            conn.close()

    def prune_low_salience(self, min_salience: float = 0.05) -> int:
        """修剪低显著性记忆"""
        conn = sqlite3.connect(self.db_path)
        try:
            # 计算显著性并删除低分记忆
            cursor = conn.execute("""
                DELETE FROM memories WHERE id IN (
                    SELECT id FROM memories
                    WHERE importance < ?
                    AND (julianday('now') - julianday(created_at/86400 + 2440587.5)) > 7
                )
            """, (min_salience,))
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"[SQLiteBackend] 修剪 {deleted} 条低显著性记忆")

            return deleted
        finally:
            conn.close()

    def record_execution(self, action: str, success: bool, latency_ms: float = 0):
        """记录执行统计"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO execution_stats (action, success, latency_ms, timestamp)
                VALUES (?, ?, ?, ?)
            """, (action, int(success), latency_ms, time.time()))
            conn.commit()
        finally:
            conn.close()

    def get_execution_stats(self, action: Optional[str] = None,
                            hours: int = 24) -> Dict:
        """获取执行统计"""
        conn = sqlite3.connect(self.db_path)
        try:
            since = time.time() - hours * 3600

            if action:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(success) as successes,
                        AVG(latency_ms) as avg_latency
                    FROM execution_stats
                    WHERE action = ? AND timestamp > ?
                """, (action, since))
            else:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(success) as successes,
                        AVG(latency_ms) as avg_latency
                    FROM execution_stats
                    WHERE timestamp > ?
                """, (since,))

            row = cursor.fetchone()
            total = row[0] or 0
            successes = row[1] or 0
            avg_latency = row[2] or 0

            return {
                "total": total,
                "successes": successes,
                "failures": total - successes,
                "success_rate": successes / total if total > 0 else 0,
                "avg_latency_ms": round(avg_latency, 2),
            }
        finally:
            conn.close()

    def stats(self) -> Dict:
        """返回数据库统计"""
        conn = sqlite3.connect(self.db_path)
        try:
            mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            emb_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            exec_count = conn.execute("SELECT COUNT(*) FROM execution_stats").fetchone()[0]

            return {
                "total_memories": mem_count,
                "total_embeddings": emb_count,
                "total_executions": exec_count,
                "db_path": self.db_path,
                "db_size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0,
            }
        finally:
            conn.close()


class PersistentMemoryManager:
    """
    持久化记忆管理器。

    整合文件后端和 SQLite 后端：
    - 工作记忆：纯内存（不持久化）
    - 短期记忆：文件后端
    - 长期记忆：SQLite 后端
    - 执行日志：文件 + SQLite
    """

    def __init__(self, data_dir: str = "data/memory"):
        self.file_backend = FileMemoryBackend(data_dir)
        self.sqlite_backend = SQLiteMemoryBackend(
            os.path.join(data_dir, "long_term.db")
        )
        logger.info(f"[PersistentMemory] 初始化: data_dir={data_dir}")

    def save_short_term(self, memories: List[Dict]):
        """保存短期记忆"""
        self.file_backend.save_short_term_memories(memories)

    def load_short_term(self) -> List[Dict]:
        """加载短期记忆"""
        return self.file_backend.load_short_term_memories()

    def save_long_term(self, entry: Dict, embedding: Optional[List[float]] = None):
        """保存长期记忆"""
        self.sqlite_backend.save_memory(entry, embedding)

    def load_long_term(self) -> List[Dict]:
        """加载长期记忆"""
        return self.sqlite_backend.load_all_memories()

    def load_embeddings(self) -> Dict[str, List[float]]:
        """加载所有向量"""
        return self.sqlite_backend.load_embeddings()

    def record_execution(self, action: str, success: bool,
                         latency_ms: float = 0, context: str = ""):
        """记录执行"""
        # 写入文件日志
        self.file_backend.append_execution_log({
            "action": action,
            "success": success,
            "latency_ms": latency_ms,
            "context": context,
            "timestamp": time.time(),
        })
        # 写入 SQLite 统计
        self.sqlite_backend.record_execution(action, success, latency_ms)

    def record_reflection(self, reflection: Dict):
        """记录反思"""
        self.file_backend.append_reflection(reflection)

    def get_execution_stats(self, action: Optional[str] = None) -> Dict:
        """获取执行统计"""
        return self.sqlite_backend.get_execution_stats(action)

    def prune(self) -> int:
        """修剪低显著性记忆"""
        return self.sqlite_backend.prune_low_salience()

    def stats(self) -> Dict:
        """返回统计"""
        return {
            "file_backend": {
                "short_term_path": self.file_backend.short_term_path,
                "execution_log_path": self.file_backend.execution_log_path,
            },
            "sqlite_backend": self.sqlite_backend.stats(),
        }
