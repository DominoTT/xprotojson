"""
数据转换器 - 将飞书二维数组转换为结构化 JSON
"""
from typing import Dict, List, Any
import json
import re
from app.services.base import BaseService
from .schema import SheetSchema


class SheetTransformer(BaseService):
    """表格数据转换器"""
    
    def __init__(self):
        super().__init__("SheetTransformer")
    
    def transform_to_structured(
        self,
        raw_values: List[List[Any]],
        schema: SheetSchema
    ) -> Dict[str, Dict[str, Any]]:
        """
        将二维数组转换为结构化数据
        
        Args:
            raw_values: 飞书返回的二维数组数据
            schema: 表格 Schema 定义
            
        Returns:
            结构化数据字典 {key: {field: value}}
            例如: {"11001": {"Name": "英雄1", "Level": 1}}
        """
        self.log_info(f"开始转换数据，共 {len(raw_values)} 行")
        
        # 验证 schema
        if not schema.validate():
            raise ValueError("无效的 Schema 配置")
        
        # 验证数据
        if not raw_values:
            self.log_warning("数据为空")
            return {}
        
        # 提取或使用提供的表头
        if schema.headers:
            headers = schema.headers
        else:
            headers = self._extract_headers(raw_values, schema.header_row)
            if not headers:
                raise ValueError("无法提取表头")
        
        # 查找主键列索引
        key_index = self._find_key_column_index(headers, schema.key_column)
        if key_index == -1:
            raise ValueError(f"未找到主键列: {schema.key_column}")
        
        # 转换数据
        result = {}
        data_start = schema.data_start_row - 1  # 转换为 0-based 索引
        
        for row_idx, row in enumerate(raw_values[data_start:], start=data_start):
            # 跳过空行
            if not row or all(self._is_empty_value(cell) for cell in row):
                continue
            
            # 获取主键值
            if key_index >= len(row):
                self.log_warning(f"行 {row_idx + 1} 缺少主键列")
                continue
                
            key_value = str(row[key_index])
            if self._is_empty_value(key_value):
                self.log_warning(f"行 {row_idx + 1} 主键为空，跳过")
                continue
            
            # 构建行数据
            row_data = {}
            for col_idx, header in enumerate(headers):
                if col_idx < len(row):
                    value = self.parse_value(row[col_idx], header, schema)
                else:
                    value = None
                row_data[header] = value
            
            # 添加到结果
            if key_value in result:
                self.log_warning(f"发现重复的主键: {key_value}，将覆盖之前的数据")
            result[key_value] = row_data
        
        self.log_info(f"转换完成，共 {len(result)} 条数据")
        self.record_metric("rows_transformed", len(result))
        
        return result
    
    def parse_value(
        self,
        value: Any,
        column: str,
        schema: SheetSchema
    ) -> Any:
        """
        解析单个值，根据类型映射进行转换
        
        Args:
            value: 原始值
            column: 列名
            schema: 表格 Schema
            
        Returns:
            转换后的值
        """
        # 处理空值
        if self._is_empty_value(value):
            return None
        
        # 转换为字符串进行处理
        str_value = str(value).strip()
        
        # 优先检查是否是特殊列类型
        if column in schema.array_columns:
            return self._parse_array_value(str_value)
        
        if column in schema.json_columns:
            return self._parse_json_value(str_value)
        
        # 获取列的类型
        col_type = schema.get_type_for_column(column)
        
        try:
            if col_type == "int":
                # 整数类型
                return int(float(str_value))
            
            elif col_type == "float":
                # 浮点数类型
                return float(str_value)
            
            elif col_type == "bool":
                # 布尔类型
                lower_val = str_value.lower()
                if lower_val in ("true", "1", "yes", "是"):
                    return True
                elif lower_val in ("false", "0", "no", "否"):
                    return False
                else:
                    return bool(str_value)
            
            elif col_type == "json" or col_type == "array":
                # JSON 类型（包括数组）
                # 处理类似 [1, 2, 3] 或 {"a": 1} 的字符串
                if str_value.startswith("[") or str_value.startswith("{"):
                    try:
                        return json.loads(str_value)
                    except json.JSONDecodeError:
                        self.log_warning(f"无法解析 JSON: {str_value}")
                        return str_value
                # 处理逗号分隔的值
                elif "," in str_value:
                    items = [item.strip() for item in str_value.split(",")]
                    # 尝试转换为数字数组
                    try:
                        return [int(item) for item in items]
                    except ValueError:
                        return items
                else:
                    return str_value
            
            else:
                # 默认为字符串类型
                return str_value
                
        except Exception as e:
            self.log_warning(f"值转换失败 {column}={value}: {e}")
            return str_value
    
    def _extract_headers(
        self,
        raw_values: List[List[Any]],
        header_row: int
    ) -> List[str]:
        """提取表头"""
        # header_row 是 1-based，需要转换为 0-based
        row_index = header_row - 1
        
        if row_index < 0 or row_index >= len(raw_values):
            raise ValueError(f"表头行 {header_row} 超出数据范围")
        
        headers = []
        for cell in raw_values[row_index]:
            if self._is_empty_value(cell):
                # 空表头使用默认名称
                headers.append(f"Column{len(headers) + 1}")
            else:
                # 清理表头名称
                header = str(cell).strip()
                # 移除特殊字符
                header = re.sub(r'[^\w\u4e00-\u9fa5]', '_', header)
                headers.append(header)
        
        return headers
    
    def _find_key_column_index(
        self,
        headers: List[str],
        key_column: str
    ) -> int:
        """查找主键列索引"""
        try:
            return headers.index(key_column)
        except ValueError:
            # 尝试忽略大小写查找
            key_lower = key_column.lower()
            for idx, header in enumerate(headers):
                if header.lower() == key_lower:
                    return idx
            return -1
    
    def _is_empty_value(self, value: Any) -> bool:
        """判断值是否为空"""
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        return False
    
    def _parse_array_value(self, value: str) -> List[Any]:
        """解析数组值"""
        if not value:
            return []
            
        # 尝试 JSON 数组解析
        if value.startswith("["):
            try:
                result = json.loads(value)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        
        # 尝试逗号分隔
        if "," in value:
            items = [item.strip() for item in value.split(",")]
            # 尝试转换为数字数组
            try:
                return [int(item) for item in items if item]
            except ValueError:
                try:
                    return [float(item) for item in items if item]
                except ValueError:
                    return items
        
        # 尝试分号分隔
        if ";" in value:
            return [item.strip() for item in value.split(";") if item.strip()]
        
        # 单个值返回数组
        return [value]
    
    def _parse_json_value(self, value: str) -> Any:
        """解析 JSON 值"""
        if not value:
            return None
            
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            self.log_warning(f"JSON 解析失败: {value}")
            # 如果是类似键值对的格式，尝试简单解析
            if ":" in value and not value.startswith("http"):
                # 简单的键值对解析
                try:
                    pairs = {}
                    for pair in value.split(","):
                        if ":" in pair:
                            k, v = pair.split(":", 1)
                            pairs[k.strip()] = v.strip()
                    return pairs if pairs else value
                except:
                    pass
            return value
    
    def transform_batch(
        self,
        sheets_data: Dict[str, List[List[Any]]],
        schemas: Dict[str, SheetSchema]
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        批量转换多个 sheet 的数据
        
        Args:
            sheets_data: {sheet_name: raw_values}
            schemas: {sheet_name: schema}
            
        Returns:
            {sheet_name: {key: {field: value}}}
        """
        result = {}
        
        for sheet_name, raw_values in sheets_data.items():
            schema = schemas.get(sheet_name)
            if not schema:
                self.log_warning(f"未找到 {sheet_name} 的 schema，跳过")
                continue
            
            try:
                result[sheet_name] = self.transform_to_structured(raw_values, schema)
            except Exception as e:
                self.log_error(f"转换 {sheet_name} 失败: {e}", error=e)
                result[sheet_name] = {}
        
        return result