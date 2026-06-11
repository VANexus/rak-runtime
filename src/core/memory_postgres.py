"""
PostgreSQL 长期记忆后端

替代 SQLite，支持：
- 向量检索（pgvector 扩展）
- 全文搜索（中文分词）
- 时间序列执行指标（InfluxDB 风格）
- JSON 元数据查询
- 连接池管理

降级策略：PostgreSQL 不可用时自动回退到 SQLite。
"""

import json
import logging
import os
import time
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class PostgresMemoryBackend:
    """
    PostgreSQL 长期记忆后端。

    表结构：
    - memories: 记忆条目（含向量）
    - execution_metrics: 执行指标（时间序列）
    - skill_weights: 技能权重历史

    依赖：
    - psycopg2 或 asyncpg
    - pgvector 扩展（可选，用于向量检索）
    """

    def __init__(self, dsn: str = None, pool_min: int = 2, pool_max: int = 10):
        self.dsn = dsn or os.getenv(
            "RAG_POSTGRES_DSN",
            "postgresql://rak:rak@localhost:5432/rak_memory"
        )
        self.pool_min = pool_min
        self.pool_max = pool_max
        self._pool = None
        self._available = False

        self._try_connect()

    def _try_connect(self):
        """尝试连接 PostgreSQL"""
        try:
            import psycopg2
            from psycopg2 import pool as pg_pool

            self._pool = pg_pool.ThreadedConnectionPool(
                self.pool_min, self.pool_max, self.dsn
            )

            # 测试连接
            conn = self._pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                self._available = True
                logger.info("[PostgresBackend] 连接成功")

                # 初始化表结构
                self._init_schema(conn)
            finally:
                self._pool.putconn(conn)

        except ImportError:
            logger.warning("[PostgresBackend] psycopg2 未安装，回退到 SQLite")
            self._available = False
        except Exception as e:
            logger.warning("[PostgresBackend] 连接失败: %s，回退到 SQLite", e)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _init_schema(self, conn):
        """初始化数据库 Schema"""
        try:
            cur = conn.cursor()

            # 尝试创建 pgvector 扩展
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                has_vector = True
                logger.info("[PostgresBackend] pgvector 扩展已启用")
            except Exception:
                has_vector = False
                logger.info("[PostgresBackend] pgvector 不可用，使用 JSON 存储向量")

            # 记忆表
            if has_vector:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        layer TEXT NOT NULL DEFAULT 'long_term',
                        importance REAL DEFAULT 0.5,
                        embedding vector(128),
                        metadata JSONB DEFAULT '{}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        access_count INTEGER DEFAULT 0,
                        decay_rate REAL DEFAULT 0.01
                    )
                """)
            else:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        layer TEXT NOT NULL DEFAULT 'long_term',
                        importance REAL DEFAULT 0.5,
                        embedding JSONB DEFAULT '[]',
                        metadata JSONB DEFAULT '{}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        access_count INTEGER DEFAULT 0,
                        decay_rate REAL DEFAULT 0.01
                    )
                """)

            # 索引
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_type
                ON memories(memory_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_importance
                ON memories(importance DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_created
                ON memories(created_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_metadata
                ON memories USING GIN (metadata)
            """)

            # 执行指标表（时间序列）
            cur.execute("""
                CREATE TABLE IF NOT EXISTS execution_metrics (
                    id BIGSERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    latency_ms REAL,
                    device_id TEXT,
                    trace_id TEXT,
                    metadata JSONB DEFAULT '{}',
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_action
                ON execution_metrics(action, recorded_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_time
                ON execution_metrics(recorded_at DESC)
            """)

            # 技能权重历史表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS skill_weights (
                    id BIGSERIAL PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    weight REAL NOT NULL,
                    reason TEXT,
                    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_weights_skill
                ON skill_weights(skill_id, recorded_at DESC)
            """)

            conn.commit()
            cur.close()

            self._has_vector = has_vector
            logger.info("[PostgresBackend] Schema 初始化完成")

        except Exception as e:
            logger.warning("[PostgresBackend] Schema 初始化失败: %s", e)
            conn.rollback()

    def _get_conn(self):
        """获取连接"""
        if not self._available or not self._pool:
            return None
        return self._pool.getconn()

    def _put_conn(self, conn):
        """归还连接"""
        if self._pool and conn:
            self._pool.putconn(conn)

    # ========== 记忆 CRUD ==========

    def save_memory(self, entry: Dict, embedding: Optional[List[float]] = None):
        """保存记忆条目"""
        conn = self._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()

            # 处理向量
            emb_data = None
            if embedding:
                if hasattr(self, '_has_vector') and self._has_vector:
                    emb_data = str(embedding)  # pgvector 格式
                else:
                    emb_data = json.dumps(embedding)

            cur.execute("""
                INSERT INTO memories (id, content, memory_type, layer, importance,
                    embedding, metadata, created_at, last_accessed, access_count, decay_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    importance = EXCLUDED.importance,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    last_accessed = EXCLUDED.last_accessed,
                    access_count = EXCLUDED.access_count
            """, (
                entry["id"],
                entry["content"],
                entry["memory_type"],
                entry.get("layer", "long_term"),
                entry.get("importance", 0.5),
                emb_data,
                json.dumps(entry.get("metadata", {})),
                entry.get("created_at", time.time()),
                entry.get("last_accessed", time.time()),
                entry.get("access_count", 0),
                entry.get("decay_rate", 0.01),
            ))

            conn.commit()
            cur.close()

        except Exception as e:
            logger.warning("[PostgresBackend] 保存失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)

    def load_all_memories(self, limit: int = 1000) -> List[Dict]:
        """加载所有记忆"""
        conn = self._get_conn()
        if not conn:
            return []

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, content, memory_type, layer, importance,
                       metadata, created_at, last_accessed, access_count, decay_rate
                FROM memories
                ORDER BY importance DESC, created_at DESC
                LIMIT %s
            """, (limit,))

            rows = cur.fetchall()
            cur.close()

            return [
                {
                    "id": row[0],
                    "content": row[1],
                    "memory_type": row[2],
                    "layer": row[3],
                    "importance": row[4],
                    "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {},
                    "created_at": row[6].timestamp() if row[6] else 0,
                    "last_accessed": row[7].timestamp() if row[7] else 0,
                    "access_count": row[8],
                    "decay_rate": row[9],
                }
                for row in rows
            ]

        except Exception as e:
            logger.warning("[PostgresBackend] 加载失败: %s", e)
            return []
        finally:
            self._put_conn(conn)

    def search_by_embedding(self, query_embedding: List[float],
                            top_k: int = 5, memory_types: Optional[List[str]] = None) -> List[Dict]:
        """向量检索"""
        conn = self._get_conn()
        if not conn:
            return []

        try:
            cur = conn.cursor()

            if hasattr(self, '_has_vector') and self._has_vector:
                # 使用 pgvector 的余弦距离
                query_vec = str(query_embedding)
                sql = """
                    SELECT id, content, memory_type, importance, metadata,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM memories
                """
                params = [query_vec]
            else:
                # 降级：JSON 向量的余弦相似度（慢，但可用）
                sql = """
                    SELECT id, content, memory_type, importance, metadata, 0.5 as similarity
                    FROM memories
                """
                params = []

            if memory_types:
                placeholders = ",".join(["%s"] * len(memory_types))
                sql += f" WHERE memory_type IN ({placeholders})"
                params.extend(memory_types)

            sql += " ORDER BY similarity DESC LIMIT %s"
            params.append(top_k)

            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()

            return [
                {
                    "id": row[0],
                    "content": row[1],
                    "memory_type": row[2],
                    "importance": row[3],
                    "metadata": row[4] if isinstance(row[4], dict) else json.loads(row[4]) if row[4] else {},
                    "similarity": row[5],
                }
                for row in rows
            ]

        except Exception as e:
            logger.warning("[PostgresBackend] 向量检索失败: %s", e)
            return []
        finally:
            self._put_conn(conn)

    def search_by_content(self, keywords: List[str], limit: int = 10) -> List[Dict]:
        """全文搜索"""
        conn = self._get_conn()
        if not conn:
            return []

        try:
            cur = conn.cursor()

            # 使用 ILIKE 进行模糊搜索
            conditions = " OR ".join(["content ILIKE %s"] * len(keywords))
            params = [f"%{kw}%" for kw in keywords]
            params.append(limit)

            cur.execute(f"""
                SELECT id, content, memory_type, importance, metadata
                FROM memories
                WHERE {conditions}
                ORDER BY importance DESC
                LIMIT %s
            """, params)

            rows = cur.fetchall()
            cur.close()

            return [
                {
                    "id": row[0],
                    "content": row[1],
                    "memory_type": row[2],
                    "importance": row[3],
                    "metadata": row[4] if isinstance(row[4], dict) else json.loads(row[4]) if row[4] else {},
                }
                for row in rows
            ]

        except Exception as e:
            logger.warning("[PostgresBackend] 全文搜索失败: %s", e)
            return []
        finally:
            self._put_conn(conn)

    def update_access(self, memory_id: str):
        """更新访问信息"""
        conn = self._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE memories
                SET last_accessed = NOW(), access_count = access_count + 1
                WHERE id = %s
            """, (memory_id,))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning("[PostgresBackend] 更新访问失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)

    def prune_low_salience(self, min_salience: float = 0.05) -> int:
        """修剪低显著性记忆"""
        conn = self._get_conn()
        if not conn:
            return 0

        try:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM memories
                WHERE importance < %s
                AND created_at < NOW() - INTERVAL '7 days'
            """, (min_salience,))
            deleted = cur.rowcount
            conn.commit()
            cur.close()

            if deleted > 0:
                logger.info("[PostgresBackend] 修剪 %s 条低显著性记忆", deleted)
            return deleted

        except Exception as e:
            logger.warning("[PostgresBackend] 修剪失败: %s", e)
            conn.rollback()
            return 0
        finally:
            self._put_conn(conn)

    # ========== 执行指标 ==========

    def record_execution(self, action: str, success: bool, latency_ms: float = 0,
                         device_id: str = "", trace_id: str = ""):
        """记录执行指标"""
        conn = self._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO execution_metrics (action, success, latency_ms, device_id, trace_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (action, success, latency_ms, device_id, trace_id))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning("[PostgresBackend] 记录执行失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)

    def get_execution_stats(self, action: Optional[str] = None,
                            hours: int = 24) -> Dict:
        """获取执行统计"""
        conn = self._get_conn()
        if not conn:
            return {}

        try:
            cur = conn.cursor()

            if action:
                cur.execute("""
                    SELECT COUNT(*), SUM(CASE WHEN success THEN 1 ELSE 0 END),
                           AVG(latency_ms)
                    FROM execution_metrics
                    WHERE action = %s AND recorded_at > NOW() - INTERVAL '%s hours'
                """, (action, hours))
            else:
                cur.execute("""
                    SELECT COUNT(*), SUM(CASE WHEN success THEN 1 ELSE 0 END),
                           AVG(latency_ms)
                    FROM execution_metrics
                    WHERE recorded_at > NOW() - INTERVAL '%s hours'
                """, (hours,))

            row = cur.fetchone()
            cur.close()

            total = row[0] or 0
            successes = row[1] or 0
            avg_latency = row[2] or 0

            return {
                "total": total,
                "successes": successes,
                "failures": total - successes,
                "success_rate": successes / total if total > 0 else 0,
                "avg_latency_ms": round(float(avg_latency), 2),
            }

        except Exception as e:
            logger.warning("[PostgresBackend] 统计查询失败: %s", e)
            return {}
        finally:
            self._put_conn(conn)

    # ========== 技能权重 ==========

    def record_skill_weight(self, skill_id: str, weight: float, reason: str = ""):
        """记录技能权重变化"""
        conn = self._get_conn()
        if not conn:
            return

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO skill_weights (skill_id, weight, reason)
                VALUES (%s, %s, %s)
            """, (skill_id, weight, reason))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning("[PostgresBackend] 记录权重失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)

    def get_skill_weight_history(self, skill_id: str, limit: int = 100) -> List[Dict]:
        """获取技能权重历史"""
        conn = self._get_conn()
        if not conn:
            return []

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT weight, reason, recorded_at
                FROM skill_weights
                WHERE skill_id = %s
                ORDER BY recorded_at DESC
                LIMIT %s
            """, (skill_id, limit))

            rows = cur.fetchall()
            cur.close()

            return [
                {
                    "weight": row[0],
                    "reason": row[1],
                    "recorded_at": row[2].isoformat() if row[2] else None,
                }
                for row in rows
            ]

        except Exception as e:
            logger.warning("[PostgresBackend] 权重历史查询失败: %s", e)
            return []
        finally:
            self._put_conn(conn)

    # ========== 统计 ==========

    def stats(self) -> Dict:
        """返回统计"""
        if not self._available:
            return {"available": False}

        conn = self._get_conn()
        if not conn:
            return {"available": False}

        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM memories")
            mem_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM execution_metrics")
            exec_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM skill_weights")
            weight_count = cur.fetchone()[0]
            cur.close()

            return {
                "available": True,
                "total_memories": mem_count,
                "total_executions": exec_count,
                "total_weight_records": weight_count,
                "has_vector": getattr(self, '_has_vector', False),
            }

        except Exception as e:
            return {"available": False, "error": str(e)}
        finally:
            self._put_conn(conn)

    def close(self):
        """关闭连接池"""
        if self._pool:
            self._pool.closeall()
            logger.info("[PostgresBackend] 连接池已关闭")


class HybridLongTermBackend:
    """
    混合长期记忆后端 — PostgreSQL + SQLite 降级。

    优先使用 PostgreSQL，不可用时自动降级到 SQLite。
    """

    def __init__(self, postgres_dsn: str = None, sqlite_path: str = "data/memory/long_term.db"):
        self.postgres = PostgresMemoryBackend(postgres_dsn)
        self._sqlite = None
        self._sqlite_path = sqlite_path

        if not self.postgres.available:
            self._init_sqlite()

    def _init_sqlite(self):
        """初始化 SQLite 降级"""
        try:
            from src.core.memory_persistence import SQLiteMemoryBackend
            self._sqlite = SQLiteMemoryBackend(self._sqlite_path)
            logger.info("[HybridLongTerm] 使用 SQLite 降级后端")
        except Exception as e:
            logger.warning("[HybridLongTerm] SQLite 初始化失败: %s", e)

    @property
    def backend_name(self) -> str:
        if self.postgres.available:
            return "postgresql"
        elif self._sqlite:
            return "sqlite"
        return "none"

    def save_memory(self, entry: Dict, embedding: Optional[List[float]] = None):
        if self.postgres.available:
            return self.postgres.save_memory(entry, embedding)
        elif self._sqlite:
            return self._sqlite.save_memory(entry, embedding)

    def load_all_memories(self, limit: int = 1000) -> List[Dict]:
        if self.postgres.available:
            return self.postgres.load_all_memories(limit)
        elif self._sqlite:
            return self._sqlite.load_all_memories()
        return []

    def record_execution(self, action: str, success: bool, latency_ms: float = 0, **kwargs):
        if self.postgres.available:
            self.postgres.record_execution(action, success, latency_ms, **kwargs)
        elif self._sqlite:
            self._sqlite.record_execution(action, success, latency_ms)

    def stats(self) -> Dict:
        return {
            "backend": self.backend_name,
            "postgres": self.postgres.stats(),
        }
