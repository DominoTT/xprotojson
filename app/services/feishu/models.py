"""
飞书相关数据模型
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class FileInfo:
    """文件信息模型"""
    token: str  # 文件 token
    name: str  # 文件名
    type: str  # 文件类型 (sheet, doc, folder 等)
    parent_token: str  # 父文件夹 token
    created_time: int  # 创建时间（与飞书 API 一致，数字时间戳）
    modified_time: int  # 修改时间（与飞书 API 一致，数字时间戳）
    
    @classmethod
    def from_api_response(cls, data: Any) -> 'FileInfo':
        """从飞书 Drive 文件列表 API 的字典创建实例（按标准结构）。

        仅针对飞书 `file.list` 返回的数据结构取值：
        - token
        - name
        - type
        - parent_token
        - created_time（字符串/数字时间戳：秒或毫秒）
        - modified_time（字符串/数字时间戳：秒或毫秒）
        - 若为 `shortcut`，将解析 `shortcut_info` 并用目标 token 替换，按 token 前缀推断目标类型
        """
        def _g(obj: Any, key: str) -> Optional[Any]:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        def _parse_num_ts(v: Any) -> int:
            """解析时间戳为整数（不做单位转换，保持与原始数据一致）。"""
            if v is None:
                return 0
            if isinstance(v, bool):
                return 0
            if isinstance(v, (int, float)):
                try:
                    return int(v)
                except Exception:
                    return 0
            if isinstance(v, str):
                s = v.strip()
                try:
                    # 直接按数字字符串解析
                    return int(float(s))
                except Exception:
                    return 0
            return 0

        token = _g(data, "token") or ""
        name = _g(data, "name") or ""
        parent_token = _g(data, "parent_token") or ""

        file_type = _g(data, "type")
        file_type = (file_type or "").lower()

        created_raw = _g(data, "created_time")
        modified_raw = _g(data, "modified_time")

        # 处理快捷方式：用目标 token 替换，并尽量推断目标类型
        if file_type == "shortcut":
            si = _g(data, "shortcut_info")
            target_token = None
            target_type = None
            if isinstance(si, dict):
                target_token = si.get("target_token")
                target_type = si.get("target_type")
            elif si is not None:
                target_token = getattr(si, "target_token", None)
                target_type = getattr(si, "target_type", None)

            if isinstance(target_token, str) and target_token:
                token = target_token
                # 根据 token 前缀推断类型（无需 service 层再处理）
                lt = token.lower()
                if lt.startswith("sht"):
                    file_type = "sheet"
                elif lt.startswith("dox"):
                    file_type = "docx"
                elif lt.startswith("box"):
                    file_type = "file"
                elif isinstance(target_type, str) and target_type:
                    file_type = target_type.lower()

        return cls(
            token=token,
            name=name,
            type=file_type,
            parent_token=parent_token,
            created_time=_parse_num_ts(created_raw),
            modified_time=_parse_num_ts(modified_raw),
        )
    
    def is_sheet(self) -> bool:
        """判断是否为表格文件"""
        return self.type.lower() in ["sheet", "spreadsheet", "bitable"]


@dataclass
class SheetMeta:
    """表格元数据模型"""
    sheet_id: str  # Sheet ID
    sheet_name: str  # Sheet 名称
    revision: int  # 版本号
    last_modified: datetime  # 最后修改时间
    dimensions: Dict[str, int]  # 维度信息 {"rows": 100, "cols": 26}
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'SheetMeta':
        """从飞书 API 响应创建实例"""
        sheet_info = data.get("sheet", {})
        properties = sheet_info.get("properties", {})
        
        return cls(
            sheet_id=sheet_info.get("sheet_id", ""),
            sheet_name=properties.get("title", ""),
            revision=data.get("revision", 0),
            last_modified=datetime.now(),  # 飞书 API 可能不返回此字段
            dimensions={
                "rows": properties.get("row_count", 0),
                "cols": properties.get("column_count", 0)
            }
        )


@dataclass
class SheetValueRange:
    """表格值范围"""
    range: str  # 范围字符串，如 "A1:Z100"
    major_dimension: str  # 主要维度 ROWS/COLUMNS
    values: List[List[Any]]  # 二维数组数据
    revision: int  # 数据版本号
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'SheetValueRange':
        """从飞书 API 响应创建实例"""
        value_range = data.get("valueRange", {})
        
        return cls(
            range=value_range.get("range", ""),
            major_dimension=value_range.get("majorDimension", "ROWS"),
            values=value_range.get("values", []),
            revision=value_range.get("revision", data.get("revision", 0))
        )
    
    def is_empty(self) -> bool:
        """判断数据是否为空"""
        return not self.values or all(not row for row in self.values)
    
    def get_row_count(self) -> int:
        """获取行数"""
        return len(self.values)
    
    def get_col_count(self) -> int:
        """获取列数"""
        if not self.values:
            return 0
        return max(len(row) for row in self.values)


@dataclass 
class DriveListResponse:
    """Drive 文件列表响应"""
    files: List[FileInfo]
    has_more: bool
    next_page_token: Optional[str]
    
    @classmethod
    def from_api_response(cls, data: Any) -> 'DriveListResponse':
        """从飞书 Drive 列表响应对象或字典创建实例。

        兼容 lark-oapi 的 ListFileResponseBody（属性访问）与 dict 结构。
        顶层也可能包裹在 {"data": {...}}。
        """
        # 解包顶层 data
        payload = data
        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], (dict, object)):
            payload = payload["data"]

        # 取文件列表
        files_raw = None
        if isinstance(payload, dict):
            files_raw = payload.get("files") or payload.get("items")
        if files_raw is None:
            files_raw = getattr(payload, "files", None) or getattr(payload, "items", None)
        files_raw = files_raw or []

        files: List[FileInfo] = []
        for item in files_raw:
            try:
                files.append(FileInfo.from_api_response(item))
            except Exception:
                continue

        # has_more / next_page_token 兼容
        if isinstance(payload, dict):
            has_more = bool(payload.get("has_more", False))
            next_token = payload.get("next_page_token") or payload.get("page_token")
        else:
            has_more = bool(getattr(payload, "has_more", False))
            next_token = getattr(payload, "next_page_token", None) or getattr(payload, "page_token", None)

        return cls(files=files, has_more=has_more or bool(next_token), next_page_token=next_token)
