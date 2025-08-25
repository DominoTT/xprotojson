"""
表格 Schema 和配置模型定义
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple, Any
import re


@dataclass
class SheetSchema:
    """表格 Schema 定义，描述如何解析表格数据"""
    key_column: str  # 主键列名，如 "ID"
    headers: List[str] = field(default_factory=list)  # 列名列表，可选（自动从表头提取）
    header_row: int = 1  # 表头所在行（1-based）
    data_start_row: int = 2  # 数据开始行（1-based）
    type_mapping: Dict[str, str] = field(default_factory=dict)  # 列类型映射 {"ID": "int", "Name": "str"}
    array_columns: List[str] = field(default_factory=list)  # 数组类型的列
    json_columns: List[str] = field(default_factory=list)  # JSON 类型的列
    
    def get_type_for_column(self, column: str) -> str:
        """获取列的类型，默认为 str"""
        return self.type_mapping.get(column, "str")
    
    def validate(self) -> bool:
        """验证 Schema 是否有效"""
        if not self.key_column:
            return False
        if self.header_row < 1 or self.data_start_row < 1:
            return False
        if self.data_start_row <= self.header_row:
            return False
        return True


@dataclass
class SheetRange:
    """表格范围定义"""
    sheet_id: Optional[str] = None  # Sheet ID（可选）
    start_row: int = 1  # 起始行（1-based）
    end_row: Optional[int] = None  # 结束行（None 表示到最后）
    start_col: str = "A"  # 起始列
    end_col: Optional[str] = None  # 结束列（None 表示到最后）
    
    def to_a1_notation(self, sheet_name: Optional[str] = None) -> str:
        """
        转换为 A1 表示法
        
        Args:
            sheet_name: Sheet 名称
            
        Returns:
            A1 表示法字符串，如 "Sheet1!A1:Z100"
        """
        # 构建范围字符串
        range_str = f"{self.start_col}{self.start_row}"
        
        if self.end_col and self.end_row:
            range_str += f":{self.end_col}{self.end_row}"
        elif self.end_col:
            range_str += f":{self.end_col}"
        elif self.end_row:
            range_str += f":{self.start_col}{self.end_row}"
        
        # 添加 sheet 名称
        if sheet_name:
            # 如果 sheet 名称包含特殊字符，需要用单引号包裹
            if any(char in sheet_name for char in [' ', '!', '(', ')']):
                sheet_name = f"'{sheet_name}'"
            range_str = f"{sheet_name}!{range_str}"
        
        return range_str
    
    @classmethod
    def from_a1_notation(cls, a1_str: str) -> 'SheetRange':
        """从 A1 表示法创建 SheetRange"""
        # 分离 sheet 名称和范围
        sheet_name = None
        range_part = a1_str
        
        if '!' in a1_str:
            sheet_name, range_part = a1_str.split('!', 1)
            # 去除可能的引号
            sheet_name = sheet_name.strip("'")
        
        # 解析范围
        pattern = r'^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$'
        match = re.match(pattern, range_part)
        
        if not match:
            raise ValueError(f"无效的 A1 表示法: {a1_str}")
        
        start_col, start_row, end_col, end_row = match.groups()
        
        return cls(
            sheet_id=sheet_name,
            start_row=int(start_row),
            end_row=int(end_row) if end_row else None,
            start_col=start_col,
            end_col=end_col
        )


class SheetSchemaBuilder:
    """集中负责：
    - 按 settings.table 的行定义（name/type/comment/data_start）解析 schema
    - 解析 proto3 类型，生成类型映射、数组/JSON 列集合
    - 计算并返回 kept_indices（非空列名的原始列索引）
    """

    def __init__(self, settings_table) -> None:
        self._cfg = settings_table

    def infer(self, raw_values: List[List[Any]]) -> Tuple[SheetSchema, List[int]]:
        cfg = self._cfg
        header_row = cfg.header_name_row + 1
        data_start_row = cfg.data_start_row + 1

        headers: List[str] = []
        kept_indices: List[int] = []

        if raw_values and len(raw_values) > cfg.header_name_row:
            name_row = raw_values[cfg.header_name_row]
            for idx, cell in enumerate(name_row):
                if self._is_empty(cell):
                    continue
                h = self._clean(str(cell))
                if not h:
                    continue
                kept_indices.append(idx)
                headers.append(h)

        # 类型行优先
        types_row: List[Any] = raw_values[cfg.type_row] if len(raw_values) > cfg.type_row else []
        type_mapping: Dict[str, str] = {}
        array_columns: List[str] = []
        json_columns: List[str] = []

        for pos, header in enumerate(headers):
            src_idx = kept_indices[pos] if pos < len(kept_indices) else pos
            tcell = types_row[src_idx] if src_idx < len(types_row) else None
            base_type, elem_type = self._parse_proto3_type(str(tcell) if tcell is not None else "")
            if base_type == "auto":
                # 空类型，兜底推断：使用下方样本行，但仅作为最后手段
                samples: List[Any] = []
                for r in range(cfg.header_name_row + 1, min(len(raw_values), cfg.comment_row + 1)):
                    row = raw_values[r]
                    samples.append(row[src_idx] if src_idx < len(row) else None)
                base_type = self._infer_from_samples(samples)

            type_mapping[header] = base_type
            if base_type == "array":
                array_columns.append(header)
            elif base_type == "json":
                json_columns.append(header)

        # 主键列
        key_column = cfg.default_key_column or "ID"
        if headers:
            lower_headers = [h.lower() for h in headers]
            dk = (cfg.default_key_column or "ID").lower()
            if dk in lower_headers:
                key_column = headers[lower_headers.index(dk)]
            else:
                key_column = headers[0]

        if len(raw_values) <= cfg.data_start_row:
            data_start_row = max(header_row + 1, len(raw_values))

        schema = SheetSchema(
            key_column=key_column,
            headers=headers,
            header_row=header_row,
            data_start_row=data_start_row,
            type_mapping=type_mapping,
            array_columns=array_columns,
            json_columns=json_columns,
        )

        return schema, kept_indices

    # ---------- helpers ----------
    def _is_empty(self, v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str) and v.strip() == "":
            return True
        return False

    def _clean(self, s: str) -> str:
        s = s.strip()
        s = re.sub(r"[^\w\u4e00-\u9fa5]", "_", s)
        s = re.sub(r"_+", "_", s).strip("_")
        return s

    def _parse_proto3_type(self, s: str) -> Tuple[str, Optional[str]]:
        t = (s or "").strip().lower()
        if not t:
            return "auto", None
        import re as _re
        m = _re.match(r"repeated\s*<\s*([\w\d]+)\s*>", t)
        if m:
            return "array", self._map_base(m.group(1))
        m = _re.match(r"([\w\d]+)\s*\[\s*\]", t)
        if m:
            return "array", self._map_base(m.group(1))
        if t.startswith("map<") or t.startswith("message") or t == "json":
            return "json", None
        return self._map_base(t), None

    def _map_base(self, b: str) -> str:
        x = (b or "").lower()
        if x in {"int32","int64","sint32","sint64","uint32","uint64"}: return "int"
        if x in {"float","double"}: return "float"
        if x == "bool": return "bool"
        if x == "string": return "str"
        if x == "bytes": return "bytes"
        return "str"

    def _infer_from_samples(self, samples: List[Any]) -> str:
        has_json = has_array = has_bool = has_int = has_float = False
        for v in samples:
            if v is None or (isinstance(v, str) and v.strip() == ""):
                continue
            s = str(v).strip()
            if s.startswith("{") and s.endswith("}"):
                has_json = True; continue
            if s.startswith("[") and s.endswith("]"):
                has_array = True; continue
            if "," in s or ";" in s:
                has_array = True
            lv = s.lower()
            if lv in ("true","false","1","0","yes","no","是","否"):
                has_bool = True; continue
            try:
                iv = int(float(s)); fv = float(s)
                if float(iv) == fv: has_int = True
                else: has_float = True
                continue
            except Exception:
                try:
                    float(s); has_float = True; continue
                except Exception:
                    pass
        if has_json: return "json"
        if has_array: return "array"
        if has_bool: return "bool"
        if has_int: return "int"
        if has_float: return "float"
        return "str"


@dataclass
class SheetConfig:
    """表格配置，包含获取和解析表格所需的所有信息"""
    sheet_token: str  # 表格 token
    sheet_name: str  # Sheet 名称
    range_str: str  # 范围字符串，如 "A1:Z1000"
    schema: SheetSchema  # 表格 Schema
    group_name: Optional[str] = None  # 组名，如 "Config_Unit"
    sub_type: Optional[str] = None  # 子类型，如 "hero"、"soldier"
    ttl: int = 1800  # 缓存 TTL（秒），默认 30 分钟
    
    def get_full_range(self) -> str:
        """获取完整的范围字符串，包含 sheet 名称"""
        if '!' in self.range_str:
            return self.range_str
        return f"{self.sheet_name}!{self.range_str}"
