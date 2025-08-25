"""
Sheet 同步服务：读取指定 spreadsheet_token 的首个（或指定）Sheet，
基于表格顶部前四行推断 JSON Schema，将每行数据解析为 JSON 并写入 Redis。
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from app.services.base import BaseService
from app.services.feishu import SheetService
from app.services.cache import RedisService, CacheKeys
from app.services.index_builder import IndexBuilder
from app.services.merge.rules import identify_group_and_sub
from app.services.transform import SheetTransformer, SheetSchema
from app.services.transform.schema import SheetSchemaBuilder
from app.core.config import settings


class SheetSyncService(BaseService):
    """Sheet 同步到 Redis 的服务"""

    def __init__(
        self,
        sheet_service: SheetService,
        redis_service: RedisService,
        transformer: SheetTransformer,
    ) -> None:
        super().__init__("SheetSyncService")
        self.sheet_service = sheet_service
        self.redis = redis_service
        self.transformer = transformer
        # 用于维护 ids/gids/gcount/gstate
        self.index = IndexBuilder(redis_service)

    async def sync_sheet(
        self,
        spreadsheet_token: str,
    ) -> Dict[str, Any]:
        """同步指定表格的数据到 Redis。

        - 自动获取 Sheet 元信息（含行列数、revision 等）
        - 读取 A1 到末尾（按元信息行列数构造范围）
        - 依据前四行推断 Schema（表头与类型映射）
        - 从第 5 行开始逐行解析并写入 Redis
        - 同时写入 meta 与 schema
        """

        # 1) 列出工作簿内所有 sheet
        list_resp = await self._list_sheets(spreadsheet_token)
        sheets = list_resp.get("sheets", [])

        per_sheet_results: List[Dict[str, Any]] = []
        total_rows_written = 0
            
        for s in sheets:
            sheet_id = s.get("sheet_id") or s.get("sheetId") or ""
            sheet_title = s.get("title") or s.get("name") or sheet_id or "Sheet1"
            # 解析 base_table 与 table_group（形如 Base(Group)）
            table_group = self._extract_table_group(sheet_title)
            base_table = self._strip_group_from_table_name(sheet_title)
            # 如果没有括号组名，使用默认组
            if not table_group:
                table_group = "default"
            gp = s.get("grid_properties", {}) or {}
            rows = int(gp.get("row_count", 0) or 0)
            cols = int(gp.get("column_count", 0) or 0)
            rows = max(rows, 1)
            cols = max(cols, 1)

            a1_range_by_id = f"{sheet_id}!A1:{self._col_number_to_letters(cols)}{rows}"

            # 2) 读取数据（values）：只使用 sheet_id 形式，符合 Feishu API 标准
            raw = await self.sheet_service.get_sheet_values(
                spreadsheet_token=spreadsheet_token,
                range_str=a1_range_by_id,
            )
            values_raw: List[List[Any]] = raw.get("valueRange", {}).get("values", [])

            # 3) 通过 SchemaBuilder 生成 schema 与列投影
            builder = SheetSchemaBuilder(settings.table)
            schema, kept_indices = builder.infer(values_raw)
            # 将原始二维数组按 kept_indices 投影
            values = self._project_columns(values_raw, kept_indices)

            # 4) 解析行并批量写入 Redis
            row_count, written_keys = await self._write_rows_to_redis(
                spreadsheet_token=spreadsheet_token,
                table=base_table,
                table_group=table_group,
                values=values,
                schema=schema,
            )
            total_rows_written += row_count

            # 写入 table 级 schema 与 meta（替代原先 sheet 级 schema/meta）
            await self._write_table_meta(
                table=base_table,
                schema=schema,
                spreadsheet_token=spreadsheet_token,
                sheet_id=sheet_id,
                sheet_title=sheet_title,
                table_group=table_group,
            )

            per_sheet_results.append({
                "sheet_id": sheet_id,
                "sheet_name": sheet_title,
                "rows_written": row_count,
                "schema_key": CacheKeys.table_schema_key(sheet_title),
                "row_keys_sample": written_keys[:10],
            })

        # 移除原 sheet 容器级 meta 的写入（以 table meta 取代）

        return {
            "sheet_token": spreadsheet_token,
            "total_rows_written": total_rows_written,
            "sheets": per_sheet_results,
            "note": "table meta written per sheet",
        }

    async def _write_rows_to_redis(
        self,
        spreadsheet_token: str,
        table: str,
        table_group: Optional[str],
        values: List[List[Any]],
        schema: SheetSchema,
    ) -> Tuple[int, List[str]]:
        """将数据行写入 Redis，返回成功写入的行数和键样本。"""
        if not values:
            return 0, []

        # 以 transformer 解析为结构化字典 {key: row_data}
        structured = self.transformer.transform_to_structured(values, schema)
        if not structured:
            return 0, []

        written = 0
        keys_sample: List[str] = []

        # 使用 IndexBuilder 逐行写入并维护索引
        for row_key, row_data in structured.items():
            # 仅处理可转换为整数的 ID；否则跳过并记录
            try:
                int(row_key)
            except (TypeError, ValueError):
                self.log_warning(f"跳过无效ID（非整数）: table={table}, row_id={row_key}")
                continue
            await self.index.upsert_row(
                table=table,
                row_id=row_key,
                row_data=row_data,
                group_fields=["Subtype"],
                table_group=table_group or "default",
            )
            redis_key = CacheKeys.row_cfgid_key(str(row_key))
            written += 1
            if len(keys_sample) < 20:
                keys_sample.append(redis_key)

        return written, keys_sample

    def _project_columns(self, values: List[List[Any]], kept_indices: List[int]) -> List[List[Any]]:
        if not values or not kept_indices:
            return values
        projected: List[List[Any]] = []
        for row in values:
            projected.append([row[i] if i < len(row) else None for i in kept_indices])
        return projected

    async def _write_schema_and_meta(
        self,
        spreadsheet_token: str,
        sheet_name: str,
        schema: SheetSchema,
        meta: Dict[str, Any],
    ) -> None:
        schema_key = CacheKeys.sheet_schema_key(spreadsheet_token, sheet_name)
        meta_key = CacheKeys.sheet_meta_key(spreadsheet_token)

        # 将 dataclass Schema 转为可序列化 dict
        schema_dict = {
            "key_column": schema.key_column,
            "headers": schema.headers,
            "header_row": schema.header_row,
            "data_start_row": schema.data_start_row,
            "type_mapping": schema.type_mapping,
            "array_columns": schema.array_columns,
            "json_columns": schema.json_columns,
        }
        await self.redis.set(schema_key, schema_dict)
        await self.redis.set(meta_key, meta)

    async def _write_schema(
        self,
        spreadsheet_token: str,
        sheet_name: str,
        schema: SheetSchema,
    ) -> None:
        schema_key = CacheKeys.sheet_schema_key(spreadsheet_token, sheet_name)
        schema_dict = {
            "key_column": schema.key_column,
            "headers": schema.headers,
            "header_row": schema.header_row,
            "data_start_row": schema.data_start_row,
            "type_mapping": schema.type_mapping,
            "array_columns": schema.array_columns,
            "json_columns": schema.json_columns,
        }
        await self.redis.set(schema_key, schema_dict)



    async def _write_table_meta(
        self,
        table: str,
        schema: SheetSchema,
        spreadsheet_token: str,
        sheet_id: str,
        sheet_title: str,
        table_group: Optional[str] = None,
    ) -> None:
        """写入精简 table meta（包含 sources 与 ids_key 软引用）。不再写入 xpj:schema:{table}。"""
        # 1) 生成 columns（类型映射）
        def _map_type(t: str) -> str:
            t_lower = (t or "").strip().lower()
            # 归一化整数类型
            if t_lower in {
                "int", "int32", "int64", "sint32", "sint64",
                "uint", "uint32", "uint64", "integer", "i32", "i64",
            }:
                return "int"
            # 归一化浮点类型（含 fp32/fp64/decimal/number）
            if t_lower in {"float", "double", "fp32", "fp64", "number", "decimal"}:
                return "float"
            # 其它一律按字符串处理（包括 bool/array/json/bytes 等，在表 meta 层不细分）
            return "str"

        columns: List[Dict[str, Any]] = []
        for name in (schema.headers or []):
            columns.append({"name": name, "type": _map_type(schema.type_mapping.get(name, "str"))})

        # 2) 读取历史 meta 以合并 group names 和 sources
        existing_meta: Dict[str, Any] = {}
        try:
            maybe = await self.redis.get(CacheKeys.table_meta_key(table))
            if isinstance(maybe, dict):
                existing_meta = maybe
        except Exception:
            existing_meta = {}

        old_groups = set(existing_meta.get("group_names", []) or [])
        # table_group 现在总是有值（至少是 "default"）
        old_groups.add(table_group)

        # 3) 合并 sources：避免重复，保留历史来源
        existing_sources = existing_meta.get("sources", []) or []
        existing_source_keys = {
            (s.get("spreadsheet_token"), s.get("sheet_id"), s.get("title"))
            for s in existing_sources
        }
        new_source = {
            "spreadsheet_token": spreadsheet_token,
            "sheet_id": sheet_id,
            "title": sheet_title,
            "table_group": table_group,
        }
        new_source_key = (spreadsheet_token, sheet_id, sheet_title)
        
        if new_source_key not in existing_source_keys:
            existing_sources.append(new_source)
        else:
            # 更新已存在的 source，补充 table_group
            for s in existing_sources:
                if (s.get("spreadsheet_token"), s.get("sheet_id"), s.get("title")) == new_source_key:
                    s["table_group"] = table_group
                    break

        # 4) 使用 merge 服务的组识别逻辑，兼容多种模式
        merge_group, merge_sub = identify_group_and_sub(sheet_title)
        if merge_group and merge_sub:
            # 如果符合 merge 模式，记录 sub_type
            old_groups.add(merge_sub)

        # 5) 生成 table meta
        meta: Dict[str, Any] = {
            "table": table,
            "pk": schema.key_column,
            "columns": columns,
            "schema_key": CacheKeys.table_schema_key(table),
            "sources": existing_sources,
            "sync_strategy": {"mode": "poll", "interval_sec": 60},
            "source_of_truth": "feishu",
            "owner": "",
            "ids_key": CacheKeys.table_ids_key(table),
            "table_group": table_group,
            "group_names": sorted(old_groups),
            "merge_group": merge_group,
            "merge_sub": merge_sub,
        }
        await self.redis.set(CacheKeys.table_meta_key(table), meta)




    def _col_number_to_letters(self, col_number: int) -> str:
        """1 -> A, 26 -> Z, 27 -> AA ..."""
        result = ""
        n = max(col_number, 1)
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    def _extract_table_group(self, table_name: str) -> Optional[str]:
        """提取表名中的括号组名，例如: Config_Unit_Basic(Group测试) -> Group测试"""
        try:
            name = table_name or ""
            if "(" in name and name.endswith(")"):
                start = name.rfind("(")
                return name[start + 1 : -1] or None
            return None
        except Exception:
            return None

    def _strip_group_from_table_name(self, table_name: str) -> str:
        """去除表名末尾括号部分，得到基础表名。Config_Unit_Basic(Group) -> Config_Unit_Basic"""
        try:
            name = table_name or ""
            if "(" in name and name.endswith(")"):
                start = name.rfind("(")
                return name[:start]
            return name
        except Exception:
            return table_name

    async def _list_sheets(self, spreadsheet_token: str) -> Dict[str, Any]:
        """列出工作簿内的所有 sheet，返回简化的 dict 结构。
        兼容 lark 响应对象与 dict。
        返回形如：{"sheets": [{"sheet_id": str, "title": str, "grid_properties": {"row_count": int, "column_count": int}}]}
        """
        # 直接使用底层 client，避免重复封装
        resp = await self._call_list_sheets(spreadsheet_token)
        payload = resp
        if isinstance(resp, dict):
            payload = resp.get("data", resp)
        else:
            # lark Response 对象
            try:
                payload = resp.data
            except Exception:
                payload = resp

        sheets_obj = []
        if isinstance(payload, dict):
            sheets_obj = payload.get("sheets", [])
        else:
            try:
                sheets_obj = getattr(payload, "sheets", [])
            except Exception:
                sheets_obj = []

        def _to_dict(s: Any) -> Dict[str, Any]:
            if isinstance(s, dict):
                sheet_id = s.get("sheet_id") or s.get("sheetId") or ""
                title = s.get("title") or s.get("name") or ""
                gp = s.get("grid_properties") or {}
                if not isinstance(gp, dict) and gp is not None:
                    gp = {
                        "row_count": getattr(gp, "row_count", 0),
                        "column_count": getattr(gp, "column_count", 0),
                    }
                return {
                    "sheet_id": sheet_id,
                    "title": title,
                    "grid_properties": {
                        "row_count": int((gp or {}).get("row_count", 0) or 0),
                        "column_count": int((gp or {}).get("column_count", 0) or 0),
                    },
                }
            else:
                sheet_id = getattr(s, "sheet_id", "")
                title = getattr(s, "title", "") or getattr(s, "name", "")
                gp = getattr(s, "grid_properties", None)
                row_count = 0
                col_count = 0
                if gp is not None:
                    row_count = getattr(gp, "row_count", 0) or 0
                    col_count = getattr(gp, "column_count", 0) or 0
                return {
                    "sheet_id": sheet_id,
                    "title": title,
                    "grid_properties": {
                        "row_count": int(row_count),
                        "column_count": int(col_count),
                    },
                }

        return {"sheets": [_to_dict(s) for s in (sheets_obj or [])]}

    async def _call_list_sheets(self, spreadsheet_token: str):
        # 使用 SheetService 内部 feishu_client
        # list_sheets 为同步方法，外层以 run_in_executor 调用也可；但这里直接复用 SheetService 逻辑更简单。
        # 由于 SheetService.get_sheet_meta 已经验证可调用，我们直接调用 client 方法并返回原始响应。
        loop = None
        try:
            import asyncio
            loop = asyncio.get_event_loop()
        except Exception:
            loop = None
        if loop and loop.is_running():
            return await loop.run_in_executor(None, self.sheet_service.feishu_client.list_sheets, spreadsheet_token)
        else:
            return self.sheet_service.feishu_client.list_sheets(spreadsheet_token)


