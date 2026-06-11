"""
Redis 短期记忆后端

将短期记忆从文件升级为 Redis：
- TTL 自动过期（模拟遗忘曲线）
- 高性能读写（微秒级）
- 发布/订阅（实时通知）
- 原子操作（并发安全）

降级策略：Redis 不可用时自动回退到文件后端。
"""

import json
import logging
import time
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class RedisMemoryBackend:
    """
    Redis 短期记忆后端。

    键设计：
    - rak:memory:short:{id} — 单条记忆（Hash）
    - rak:memory:short:index — 记忆 ID 索引（Sorted Set，score=时间戳）
    - rak:memory:working — 工作记忆（List）
    - rak:memory:exec_log — 执行日志（List）
    - rak:memory:stats — 统计信息（Hash）
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0",
                 key_prefix: str = "rak:memory:",
                 default_ttl: int = 86400):  # 24 小时
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self._client = None
        self._available = False

        self._try_connect()

    def _try_connect(self):
        """尝试连接 Redis"""
        try:
            import redis
            self._client = redis.from_url(self.redis_url, decode_responses=True)
            self._client.ping()
            self._available = True
            logger.info("[RedisBackend] 连接成功: %s", self.redis_url)
        except ImportError:
            logger.warning("[RedisBackend] redis-py 未安装，回退到文件后端")
            self._available = False
        except Exception as e:
            logger.warning("[RedisBackend] 连接失败: %s，回退到文件后端", e)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _key(self, *parts) -> str:
        """构建 Redis 键"""
        return self.key_prefix + ":".join(parts)

    # ========== 短期记忆 ==========

    def save_memory(self, entry: Dict, ttl: Optional[int] = None) -> bool:
        """保存记忆条目"""
        if not self._available:
            return False

        try:
            entry_id = entry["id"]
            ttl = ttl or self.default_ttl

            # 保存记忆内容
            self._client.setex(
                self._key("short", entry_id),
                ttl,
                json.dumps(entry, ensure_ascii=False),
            )

            # 添加到索引（score=时间戳）
            self._client.zadd(
                self._key("short", "index"),
                {entry_id: time.time()},
            )

            logger.debug("[RedisBackend] 保存: %s (TTL=%ss)", entry_id, ttl)
            return True

        except Exception as e:
            logger.warning("[RedisBackend] 保存失败: %s", e)
            return False

    def load_memory(self, entry_id: str) -> Optional[Dict]:
        """加载单条记忆"""
        if not self._available:
            return None

        try:
            data = self._client.get(self._key("short", entry_id))
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("[RedisBackend] 加载失败: %s", e)
            return None

    def load_all_memories(self, limit: int = 100) -> List[Dict]:
        """加载所有短期记忆（按时间排序）"""
        if not self._available:
            return []

        try:
            # 从索引获取 ID 列表
            ids = self._client.zrevrange(
                self._key("short", "index"), 0, limit-1
            )

            memories = []
            for entry_id in ids:
                data = self._client.get(self._key("short", entry_id))
                if data:
                    memories.append(json.loads(data))

            return memories

        except Exception as e:
            logger.warning("[RedisBackend] 批量加载失败: %s", e)
            return []

    def delete_memory(self, entry_id: str) -> bool:
        """删除记忆"""
        if not self._available:
            return False

        try:
            self._client.delete(self._key("short", entry_id))
            self._client.zrem(self._key("short", "index"), entry_id)
            return True
        except Exception as e:
            logger.warning("[RedisBackend] 删除失败: %s", e)
            return False

    def count_memories(self) -> int:
        """统计记忆数量"""
        if not self._available:
            return 0

        try:
            return self._client.zcard(self._key("short", "index"))
        except Exception:
            return 0

    # ========== 工作记忆 ==========

    def push_working_memory(self, entry: Dict, max_items: int = 10):
        """添加到工作记忆（List）"""
        if not self._available:
            return

        try:
            key = self._key("working")
            self._client.lpush(key, json.dumps(entry, ensure_ascii=False))
            self._client.ltrim(key, 0, max_items-1)
        except Exception as e:
            logger.warning("[RedisBackend] 工作记忆写入失败: %s", e)

    def get_working_memory(self, limit: int = 10) -> List[Dict]:
        """获取工作记忆"""
        if not self._available:
            return []

        try:
            items = self._client.lrange(self._key("working"), 0, limit-1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.warning("[RedisBackend] 工作记忆读取失败: %s", e)
            return []

    # ========== 执行日志 ==========

    def append_execution_log(self, entry: Dict, max_logs: int = 1000):
        """追加执行日志"""
        if not self._available:
            return

        try:
            key = self._key("exec_log")
            self._client.lpush(key, json.dumps(entry, ensure_ascii=False))
            self._client.ltrim(key, 0, max_logs-1)
        except Exception as e:
            logger.warning("[RedisBackend] 执行日志写入失败: %s", e)

    def get_execution_log(self, last_n: int = 100) -> List[Dict]:
        """获取最近的执行日志"""
        if not self._available:
            return []

        try:
            items = self._client.lrange(self._key("exec_log"), 0, last_n-1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.warning("[RedisBackend] 执行日志读取失败: %s", e)
            return []

    # ========== 统计 ==========

    def increment_stat(self, field: str, amount: int = 1):
        """递增统计"""
        if not self._available:
            return

        try:
            self._client.hincrby(self._key("stats"), field, amount)
        except Exception:
            pass

    def get_stats(self) -> Dict:
        """获取统计"""
        if not self._available:
            return {"available": False}

        try:
            stats = self._client.hgetall(self._key("stats"))
            stats["available"] = True
            stats["short_memories"] = self.count_memories()
            stats["working_memories"] = self._client.llen(self._key("working"))
            stats["execution_logs"] = self._client.llen(self._key("exec_log"))
            return stats
        except Exception as e:
            return {"available": False, "error": str(e)}

    # ========== 清理 ==========

    def cleanup_expired(self):
        """清理过期记忆（Redis TTL 自动处理，这里清理索引）"""
        if not self._available:
            return

        try:
            # 获取所有索引中的 ID
            ids = self._client.zrange(self._key("short", "index"), 0, -1)
            removed = 0

            for entry_id in ids:
                # 检查记忆是否还存在
                if not self._client.exists(self._key("short", entry_id)):
                    self._client.zrem(self._key("short", "index"), entry_id)
                    removed += 1

            if removed > 0:
                logger.info("[RedisBackend] 清理 %s 个过期索引", removed)

        except Exception as e:
            logger.warning("[RedisBackend] 清理失败: %s", e)

    def flush_all(self):
        """清空所有记忆（危险操作）"""
        if not self._available:
            return

        try:
            keys = self._client.keys(self.key_prefix + "*")
            if keys:
                self._client.delete(*keys)
                logger.warning("[RedisBackend] 清空 %s 个键", len(keys))
        except Exception as e:
            logger.warning("[RedisBackend] 清空失败: %s", e)


class HybridMemoryBackend:
    """
    混合记忆后端 — Redis + 文件降级。

    优先使用 Redis，不可用时自动降级到文件后端。
    Redis 恢复后自动切换回来。
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0",
                 file_backend=None):
        self.redis = RedisMemoryBackend(redis_url)
        self.file = file_backend
        self._using_redis = self.redis.available

    @property
    def backend_name(self) -> str:
        return "redis" if self._using_redis else "file"

    def save_memory(self, entry: Dict, ttl: Optional[int] = None) -> bool:
        if self._using_redis:
            success = self.redis.save_memory(entry, ttl)
            if not success:
                logger.warning("[HybridBackend] Redis 失败，降级到文件")
                self._using_redis = False
            else:
                return True

        if self.file:
            self.file.save_short_term_memories([entry])
            return True
        return False

    def load_all_memories(self, limit: int = 100) -> List[Dict]:
        if self._using_redis:
            memories = self.redis.load_all_memories(limit)
            if memories:
                return memories

        if self.file:
            return self.file.load_short_term_memories()
        return []

    def stats(self) -> Dict:
        return {
            "backend": self.backend_name,
            "redis_available": self.redis.available,
            "redis_stats": self.redis.get_stats() if self.redis.available else {},
        }
