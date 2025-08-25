"""
ZSet 有序 ID 索引构建与维护。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Iterable, Iterator, List, Dict, Optional

from app.services.base import BaseService
from app.services.cache import RedisService, CacheKeys


class IndexBuilder(BaseService):
    """为表构建/维护 ZSet 索引 xpj:ids:{table}。

    - score = Id, member = Id（字符串）
    - 所有写操作通过 pipeline
    """

    def __init__(self, redis_service: RedisService) -> None:
        super().__init__("IndexBuilder")
        self.redis = redis_service

    # -----------------------
    # 写入/更新/删除 单行 索引维护
    # -----------------------
    async def upsert_row(
        self,
        table: str,
        row_id: int | str,
        row_data: Dict[str, Any],
        group_fields: Optional[List[str]] = None,
        table_group: Optional[str] = None,
    ) -> None:
        """
        写入或更新单行，并维护：
        - xpj:cfgid:{id} 行 JSON（注入 _table）
        - xpj:ids:{table} ZSET（score=id, member=id）
        - xpj:gids:{table}:{group}:{value} ZSET（加入/迁移）
        - xpj:gcount:{table}:{group} HASH（计数增减）
        - xpj:gstate:{table}:{id} HASH（记录每个分组字段的当前值）
        """
        # 解析整数 ID，失败则忽略
        try:
            rid = int(row_id)  # type: ignore
        except (TypeError, ValueError):
            self.log_warning(f"忽略无效ID，无法转换为 int: table={table}, row_id={row_id}")
            return
        client = await self.redis._ensure_connected()
        # 注入 _table 与 group 字段（group 用于溯源表级分组）
        row_payload: Dict[str, Any] = dict(row_data)
        row_payload.setdefault("_table", table)
        # 同步行 JSON
        cfg_key = CacheKeys.row_cfgid_key(str(rid))
        ids_key = CacheKeys.table_ids_key(table)

        # 组字段默认仅处理 Subtype
        gfields = list(group_fields or ["Subtype"])
        gstate_key = CacheKeys.table_row_group_state_key(table, rid)

        # 读取旧状态
        old_states: Dict[str, Optional[str]] = {}
        try:
            if gfields:
                vals = await client.hmget(gstate_key, gfields)
                for idx, gf in enumerate(gfields):
                    old_states[gf] = vals[idx]
        except Exception:
            old_states = {}

        # 表级分组（table_group），默认为 default
        tg_new = (table_group or "").strip() or "default"
        # 将表级组名写入行数据（便于溯源）
        row_payload["_group"] = tg_new

        async with client.pipeline() as pipe:
            # 写行 & ids 索引
            await pipe.set(cfg_key, self.redis._serialize(row_payload))
            await pipe.zadd(ids_key, {str(rid): float(rid)})

            # 处理分组变更
            for gf in gfields:
                # 从行内字段获取分组值
                new_val_raw = row_payload.get(gf)
                new_val = None if new_val_raw is None or str(new_val_raw).strip() == "" else str(new_val_raw)
                old_val = old_states.get(gf)
                
                self.log_debug(f"处理分组 {gf}: table={table}, rid={rid}, old_val={old_val}, new_val={new_val}")
                
                # 如果旧值存在且与新值不同，从旧分组中移除
                if old_val and old_val != new_val:
                    old_gid_key = CacheKeys.table_group_ids_key(table, gf, old_val)
                    gcount_key = CacheKeys.table_group_count_key(table, gf)
                    await pipe.zrem(old_gid_key, str(rid))
                    await pipe.hincrby(gcount_key, old_val, -1)
                    self.log_debug(f"从旧分组移除: {old_gid_key}")
                
                # 如果新值存在且与旧值不同，加入新分组
                if new_val and new_val != old_val:
                    new_gid_key = CacheKeys.table_group_ids_key(table, gf, new_val)
                    gcount_key = CacheKeys.table_group_count_key(table, gf)
                    await pipe.zadd(new_gid_key, {str(rid): float(rid)})
                    await pipe.hincrby(gcount_key, new_val, 1)
                    self.log_debug(f"加入新分组: {new_gid_key}")
                
                # 更新 gstate
                if new_val is None:
                    await pipe.hdel(gstate_key, gf)
                else:
                    await pipe.hset(gstate_key, gf, new_val)

            # 处理表级分组（table_group）
            tg_state_field = "__tgroup__"
            tg_old = old_states.get(tg_state_field)
            if tg_old and tg_old != tg_new:
                await pipe.zrem(CacheKeys.table_tgroup_ids_key(table, tg_old), str(rid))
            if tg_new and tg_new != tg_old:
                await pipe.zadd(CacheKeys.table_tgroup_ids_key(table, tg_new), {str(rid): float(rid)})
            # 将表级组名也记录在 gstate（避免重复迁移）
            await pipe.hset(gstate_key, tg_state_field, tg_new)

            await pipe.execute()

    async def delete_row(
        self,
        table: str,
        row_id: int | str,
        group_fields: Optional[List[str]] = None,
    ) -> None:
        """删除单行及其在所有索引中的痕迹。无效 ID 将被忽略。"""
        try:
            rid = int(row_id)  # type: ignore
        except (TypeError, ValueError):
            self.log_warning(f"删除忽略：无效ID，无法转换为 int: table={table}, row_id={row_id}")
            return
        client = await self.redis._ensure_connected()
        cfg_key = CacheKeys.row_cfgid_key(str(rid))
        ids_key = CacheKeys.table_ids_key(table)
        gfields = group_fields or ["Subtype"]
        gstate_key = CacheKeys.table_row_group_state_key(table, rid)

        # 读取已有状态以便回收
        existing: Dict[str, Optional[str]] = {}
        try:
            if gfields:
                vals = await client.hmget(gstate_key, gfields)
                for idx, gf in enumerate(gfields):
                    existing[gf] = vals[idx]
        except Exception:
            existing = {}

        async with client.pipeline() as pipe:
            await pipe.delete(cfg_key)
            await pipe.zrem(ids_key, str(rid))
            for gf, val in existing.items():
                if not val:
                    continue
                gid_key = CacheKeys.table_group_ids_key(table, gf, val)
                gcount_key = CacheKeys.table_group_count_key(table, gf)
                await pipe.zrem(gid_key, str(rid))
                await pipe.hincrby(gcount_key, val, -1)
            await pipe.delete(gstate_key)
            await pipe.execute()

    async def rebuild_ids(
        self,
        table: str,
        id_iter: AsyncIterator[int] | Iterator[int],
        batch: int = 1000,
    ) -> int:
        key = CacheKeys.table_ids_key(table)
        client = await self.redis._ensure_connected()

        # 清空旧索引
        await client.delete(key)

        written = 0
        batch_items: List[int] = []

        async def _flush(items: List[int]) -> None:
            nonlocal written
            if not items:
                return
            async with client.pipeline() as pipe:
                for i in items:
                    # ZADD key score member
                    await pipe.zadd(key, {str(i): float(i)})
                await pipe.execute()
            written += len(items)

        # 兼容同步/异步迭代器
        if hasattr(id_iter, "__anext__"):
            async for i in id_iter:  # type: ignore
                batch_items.append(int(i))
                if len(batch_items) >= batch:
                    await _flush(batch_items)
                    batch_items = []
            if batch_items:
                await _flush(batch_items)
        else:
            for i in id_iter:  # type: ignore
                batch_items.append(int(i))
                if len(batch_items) >= batch:
                    await _flush(batch_items)
                    batch_items = []
            if batch_items:
                await _flush(batch_items)

        return written

    async def update_ids(
        self,
        table: str,
        add_ids: Iterable[int],
        remove_ids: Iterable[int],
    ) -> Dict[str, int]:
        key = CacheKeys.table_ids_key(table)
        client = await self.redis._ensure_connected()
        added = 0
        removed = 0
        async with client.pipeline() as pipe:
            for i in add_ids or []:
                await pipe.zadd(key, {str(int(i)): float(int(i))})
                added += 1
            for i in remove_ids or []:
                await pipe.zrem(key, str(int(i)))
                removed += 1
            await pipe.execute()

        size = int(await client.zcard(key))
        return {"added": added, "removed": removed, "size": size}

    # -----------------------
    # 查询辅助
    # -----------------------
    async def ids_count(self, table: str) -> int:
        key = CacheKeys.table_ids_key(table)
        client = await self.redis._ensure_connected()
        return int(await client.zcard(key))

    async def ids_range(self, table: str, start: int, stop: int) -> List[int]:
        key = CacheKeys.table_ids_key(table)
        client = await self.redis._ensure_connected()
        members: List[str] = await client.zrange(key, start, stop)
        return [int(m) for m in members]

    async def ids_by_score(
        self,
        table: str,
        min_score: Any,
        max_score: Any,
        limit: int = 100,
        offset: int = 0,
    ) -> List[int]:
        key = CacheKeys.table_ids_key(table)
        client = await self.redis._ensure_connected()
        members: List[str] = await client.zrangebyscore(
            key, min_score, max_score, start=offset, num=limit
        )
        return [int(m) for m in members]

    async def group_ids_range(
        self,
        table: str,
        group: str,
        value: str,
        start: int,
        stop: int,
    ) -> List[int]:
        key = CacheKeys.table_group_ids_key(table, group, value)
        client = await self.redis._ensure_connected()
        members: List[str] = await client.zrange(key, start, stop)
        return [int(m) for m in members]

    async def group_counts(self, table: str, group: str) -> Dict[str, int]:
        key = CacheKeys.table_group_count_key(table, group)
        client = await self.redis._ensure_connected()
        m: Dict[str, str] = await client.hgetall(key)
        return {k: int(v) for k, v in (m or {}).items()}

    async def scan_cfgid_ids_by_table(
        self,
        table: str,
        pattern: str = "xpj:cfgid:*",
        count: int = 1000,
    ) -> AsyncIterator[int]:
        client = await self.redis._ensure_connected()
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=count)
            if not keys:
                if cursor == 0:
                    break
            for k in keys:
                try:
                    data = await client.get(k)
                    if not data:
                        continue
                    obj = self.redis._deserialize(data)
                    if isinstance(obj, dict):
                        if obj.get("_table") == table and ("Id" in obj or "ID" in obj):
                            try:
                                vid = obj.get("Id", obj.get("ID"))
                                yield int(vid)  # type: ignore
                            except Exception:
                                continue
                except Exception:
                    continue
            if cursor == 0:
                break


