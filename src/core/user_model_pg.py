"""
用户模型 PostgreSQL 后端 — 多设备同步。

将用户画像从单机 JSON 升级为 PG 共享存储：
- 同一 user_id 的画像在多设备间共享（后写胜出，按 last_seen 仲裁）
- 不可用时自动降级本地 JSON，不崩

表设计（服务自有，与 memories 同库）：
- user_profiles: user_id 主键 + data JSONB（profile/behavior/history/corrections 全量）
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger("rak.user_model_pg")


class UserModelPostgresBackend:
    """用户画像的 PostgreSQL 存取（psycopg2 可选依赖，不可用即降级）"""

    def __init__(self, dsn: str, user_id: str = "default"):
        self._dsn = dsn
        self.user_id = user_id
        self._pool = None
        self._available = False
        try:
            import psycopg2
            from psycopg2.pool import ThreadedConnectionPool
            self._pool = ThreadedConnectionPool(1, 4, dsn)
            conn = self._pool.getconn()
            conn.cursor().execute("SELECT 1")
            conn.commit()
            self._pool.putconn(conn)
            self._available = True
            self._init_schema()
            logger.info("[UserModelPG] 已连接（user_id=%s）", user_id)
        except Exception as e:
            logger.warning("[UserModelPG] 初始化失败（降级本地 JSON）: %s", e)
            self._available = False
            if self._pool:
                try:
                    self._pool.closeall()
                except Exception:
                    pass
                self._pool = None

    @property
    def available(self) -> bool:
        return self._available

    def _init_schema(self):
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    last_seen DOUBLE PRECISION NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning("[UserModelPG] Schema 初始化失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)

    def _get_conn(self):
        if not self._available or not self._pool:
            return None
        return self._pool.getconn()

    def _put_conn(self, conn):
        if self._pool and conn:
            self._pool.putconn(conn)

    def load(self) -> Optional[Dict]:
        """读取该 user_id 的画像全量数据；无记录返回 None"""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT data FROM user_profiles WHERE user_id = %s", (self.user_id,))
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            data = row[0]
            if isinstance(data, str):
                import json
                data = json.loads(data)
            logger.info("[UserModelPG] 已加载画像 (user_id=%s)", self.user_id)
            return data
        except Exception as e:
            logger.warning("[UserModelPG] 加载失败: %s", e)
            return None
        finally:
            self._put_conn(conn)

    def save(self, data: Dict, last_seen: float = 0.0):
        """整包 upsert（后写胜出，last_seen 随包记录供多设备仲裁）"""
        conn = self._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_profiles (user_id, data, last_seen, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    data = EXCLUDED.data,
                    last_seen = EXCLUDED.last_seen,
                    updated_at = now()
            """, (self.user_id, data, last_seen))
            conn.commit()
            cur.close()
        except Exception as e:
            logger.warning("[UserModelPG] 保存失败: %s", e)
            conn.rollback()
        finally:
            self._put_conn(conn)
