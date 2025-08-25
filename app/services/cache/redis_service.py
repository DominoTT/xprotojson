"""
Redis 缓存服务
"""
from typing import Any, Optional, Callable, Awaitable
import json
import asyncio
from contextlib import asynccontextmanager
import redis.asyncio as redis
from app.services.base import BaseService, CacheError
from app.core.config import settings


class RedisService(BaseService):
    """Redis 缓存服务封装"""
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        初始化 Redis 服务
        
        Args:
            redis_url: Redis 连接 URL，不提供则从配置读取
        """
        super().__init__("RedisService")
        self.redis_url = redis_url or settings.redis.dsn
        self.redis_client: Optional[redis.Redis] = None
        self._lock = asyncio.Lock()
    
    async def _ensure_connected(self) -> redis.Redis:
        """确保 Redis 连接"""
        if self.redis_client is None:
            async with self._lock:
                if self.redis_client is None:
                    try:
                        self.redis_client = redis.from_url(
                            self.redis_url,
                            encoding="utf-8",
                            decode_responses=True
                        )
                        # 测试连接
                        await self.redis_client.ping()
                        self.log_info(f"Redis 连接成功: {self.redis_url}")
                    except Exception as e:
                        self.log_error(f"Redis 连接失败: {e}", error=e)
                        raise CacheError(
                            f"无法连接到 Redis: {str(e)}",
                            code="REDIS_CONNECTION_ERROR"
                        )
        return self.redis_client
    
    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在返回 None
        """
        try:
            client = await self._ensure_connected()
            data = await client.get(key)
            
            if data is None:
                self.log_debug(f"缓存未命中: {key}")
                return None
            
            self.log_debug(f"缓存命中: {key}")
            return self._deserialize(data)
            
        except json.JSONDecodeError as e:
            self.log_error(f"缓存数据解析失败: {key}", error=e)
            # 删除损坏的缓存
            await self.delete(key)
            return None
        except Exception as e:
            self.log_error(f"获取缓存失败: {key}", error=e)
            raise CacheError(
                f"获取缓存失败: {str(e)}",
                code="CACHE_GET_ERROR",
                details={"key": key}
            )

    async def mget(self, keys: list[str]) -> list[Optional[Any]]:
        """
        批量获取多个键的值
        
        Args:
            keys: 键列表
            
        Returns:
            值列表，不存在的键对应 None
        """
        if not keys:
            return []
            
        try:
            client = await self._ensure_connected()
            results = await client.mget(keys)
            
            # 反序列化结果
            deserialized_results = []
            for i, data in enumerate(results):
                if data is None:
                    deserialized_results.append(None)
                else:
                    try:
                        deserialized_results.append(self._deserialize(data))
                    except json.JSONDecodeError as e:
                        self.log_error(f"批量获取时数据解析失败: {keys[i]}", error=e)
                        # 删除损坏的缓存
                        await self.delete(keys[i])
                        deserialized_results.append(None)
            
            self.log_debug(f"批量获取缓存: {len(keys)} 个键")
            return deserialized_results
            
        except Exception as e:
            self.log_error(f"批量获取缓存失败", error=e)
            raise CacheError(
                f"批量获取缓存失败: {str(e)}",
                code="CACHE_MGET_ERROR",
                details={"keys": keys}
            )
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
            
        Returns:
            是否设置成功
        """
        try:
            client = await self._ensure_connected()
            data = self._serialize(value)
            
            if ttl:
                result = await client.setex(key, ttl, data)
            else:
                result = await client.set(key, data)
            
            self.log_debug(f"缓存设置成功: {key}, TTL={ttl}")
            return bool(result)
            
        except Exception as e:
            self.log_error(f"设置缓存失败: {key}", error=e)
            raise CacheError(
                f"设置缓存失败: {str(e)}",
                code="CACHE_SET_ERROR",
                details={"key": key}
            )
    
    async def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        try:
            client = await self._ensure_connected()
            result = await client.delete(key)
            self.log_debug(f"删除缓存: {key}, 结果={result}")
            return bool(result)
        except Exception as e:
            self.log_error(f"删除缓存失败: {key}", error=e)
            return False
    
    async def ttl(self, key: str) -> int:
        """
        获取键的剩余过期时间
        
        Returns:
            剩余秒数，-1 表示永不过期，-2 表示键不存在
        """
        try:
            client = await self._ensure_connected()
            return await client.ttl(key)
        except Exception as e:
            self.log_error(f"获取 TTL 失败: {key}", error=e)
            return -2
    
    async def get_or_set(
        self,
        key: str,
        fetch_func: Callable[[], Awaitable[Any]],
        ttl: Optional[int] = None
    ) -> Any:
        """
        获取缓存，不存在则调用函数获取并设置
        
        Args:
            key: 缓存键
            fetch_func: 获取数据的异步函数
            ttl: 过期时间
            
        Returns:
            缓存或新获取的数据
        """
        # 尝试从缓存获取
        cached_value = await self.get(key)
        if cached_value is not None:
            return cached_value
        
        # 使用分布式锁避免缓存击穿
        lock_key = f"{key}:lock"
        lock_acquired = False
        
        try:
            client = await self._ensure_connected()
            
            # 尝试获取锁（5秒超时）
            lock_acquired = await client.set(
                lock_key, "1", nx=True, ex=5
            )
            
            if lock_acquired:
                # 再次检查缓存（双重检查）
                cached_value = await self.get(key)
                if cached_value is not None:
                    return cached_value
                
                # 调用函数获取数据
                self.log_info(f"缓存未命中，开始获取数据: {key}")
                value = await fetch_func()
                
                # 设置缓存
                if value is not None:
                    await self.set(key, value, ttl)
                
                return value
            else:
                # 等待其他进程设置缓存
                await asyncio.sleep(0.1)
                for _ in range(50):  # 最多等待 5 秒
                    cached_value = await self.get(key)
                    if cached_value is not None:
                        return cached_value
                    await asyncio.sleep(0.1)
                
                # 超时后自己获取
                return await fetch_func()
                
        finally:
            # 释放锁
            if lock_acquired:
                await client.delete(lock_key)
    
    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        try:
            client = await self._ensure_connected()
            return bool(await client.exists(key))
        except Exception:
            return False
    
    async def expire(self, key: str, ttl: int) -> bool:
        """设置键的过期时间"""
        try:
            client = await self._ensure_connected()
            return bool(await client.expire(key, ttl))
        except Exception:
            return False
    
    async def keys(self, pattern: str) -> list[str]:
        """获取匹配模式的所有键"""
        try:
            client = await self._ensure_connected()
            return await client.keys(pattern)
        except Exception as e:
            self.log_error(f"获取键列表失败: {pattern}", error=e)
            return []
    
    async def clear_pattern(self, pattern: str) -> int:
        """删除匹配模式的所有键"""
        keys = await self.keys(pattern)
        if not keys:
            return 0
        
        try:
            client = await self._ensure_connected()
            return await client.delete(*keys)
        except Exception as e:
            self.log_error(f"批量删除失败: {pattern}", error=e)
            return 0
    
    async def close(self) -> None:
        """关闭 Redis 连接"""
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None
            self.log_info("Redis 连接已关闭")
    
    def _serialize(self, value: Any) -> str:
        """序列化数据"""
        return json.dumps(value, ensure_ascii=False, default=str)
    
    def _deserialize(self, data: str) -> Any:
        """反序列化数据"""
        return json.loads(data)
    
    @asynccontextmanager
    async def pipeline(self):
        """获取 Redis pipeline 用于批量操作"""
        client = await self._ensure_connected()
        async with client.pipeline() as pipe:
            yield pipe
