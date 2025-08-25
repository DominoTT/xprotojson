"""
飞书 Sheet 服务 - 处理表格数据读取
"""
from typing import Dict, Any, Optional, List
import asyncio
import re
from datetime import datetime
from app.services.base import BaseService, FeishuAPIError
from app.clients.feishu import FeishuClient
from .models import SheetMeta, SheetValueRange


class SheetService(BaseService):
    """飞书 Sheet 服务，负责读取表格数据"""
    
    def __init__(self, feishu_client: FeishuClient):
        """
        初始化 Sheet 服务
        
        Args:
            feishu_client: 飞书客户端实例
        """
        super().__init__("SheetService")
        self.feishu_client = feishu_client
    
    async def get_sheet_values(
        self, 
        spreadsheet_token: str,
        range_str: str,
        value_render_option: str = "ToString",
        date_time_render_option: str = "FormattedString"
    ) -> Dict[str, Any]:
        """
        获取表格指定范围的数据
        
        Args:
            spreadsheet_token: 表格 token
            range_str: 范围字符串，如 "Sheet1!A1:Z100"
            value_render_option: 值渲染选项 (ToString, Formula, UnformattedValue)
            date_time_render_option: 日期时间渲染选项
            
        Returns:
            原始飞书 API 返回，包含二维数组数据和 revision
            {
                "revision": 7,
                "valueRange": {
                    "range": "Sheet1!A1:Z100",
                    "values": [[...], [...]],
                    "revision": 7,
                    "majorDimension": "ROWS"
                }
            }
            
        Raises:
            FeishuAPIError: 飞书 API 调用失败
        """
        self.log_info(f"获取表格数据: token={spreadsheet_token}, range={range_str}")
        
        # 验证范围格式
        if not self._validate_range(range_str):
            raise ValueError(f"无效的范围格式: {range_str}")
        
        # 使用 asyncio 在异步上下文中调用同步方法
        loop = asyncio.get_event_loop()
        
        try:
            # 添加调试信息：记录请求参数
            self.log_debug(f"调用飞书 API 参数: spreadsheet_token={spreadsheet_token}, range_str={range_str}, value_render_option={value_render_option}, date_time_render_option={date_time_render_option}")
            
            # 调用飞书客户端获取数据
            values = await loop.run_in_executor(
                None,
                self.feishu_client.read_range_values,
                spreadsheet_token,
                range_str,
                value_render_option,
                date_time_render_option
            )
            
            # 添加调试信息：记录返回数据的基本信息
            self.log_debug(f"飞书 API 返回数据: 行数={len(values) if values else 0}, 第一行列数={len(values[0]) if values and len(values) > 0 else 0}")
            
            # 构造响应格式
            # 注意：read_range_values 只返回 values，我们需要构造完整响应
            response = {
                "revision": 0,  # 飞书 v2 API 可能不返回 revision
                "valueRange": {
                    "range": range_str,
                    "values": values,
                    "revision": 0,
                    "majorDimension": "ROWS"
                }
            }
            
            # 记录指标
            self.record_metric("rows_fetched", len(values))
            self.record_metric("cols_fetched", max(len(row) for row in values) if values else 0)
            
            self.log_info(f"成功获取表格数据: 行数={len(values)}, 最大列数={max(len(row) for row in values) if values else 0}")
            
            return response
            
        except Exception as e:
            # 添加详细的错误调试信息
            self.log_error(f"获取表格数据失败: token={spreadsheet_token}, range={range_str}, 错误类型={type(e).__name__}, 错误信息={str(e)}")
            
            # 如果是飞书 API 错误 90215 (not found sheetId)，提供更详细的调试信息
            if "90215" in str(e) or "not found sheetId" in str(e):
                self.log_error(f"飞书 API 错误 90215 - Sheet ID 未找到。可能原因:")
                self.log_error(f"1. range_str 格式问题: {range_str}")
                self.log_error(f"2. Sheet 名称或 ID 不存在")
                self.log_error(f"3. 权限不足或 token 无效")
                
                # 尝试解析 range_str 中的 sheet 部分
                if "!" in range_str:
                    sheet_part = range_str.split("!")[0]
                    self.log_error(f"解析的 Sheet 标识符: '{sheet_part}'")
                    
                    # 检查是否包含特殊字符或格式问题
                    if sheet_part.startswith("'") and sheet_part.endswith("'"):
                        self.log_error(f"使用了单引号包围的 Sheet 名称: {sheet_part}")
                    elif sheet_part.isdigit() or (len(sheet_part) > 5 and not sheet_part.startswith("Sheet")):
                        self.log_error(f"疑似使用了 Sheet ID 而非名称: {sheet_part}")
            
            self._handle_api_error(e)
    
    async def get_sheet_meta(
        self,
        spreadsheet_token: str,
        sheet_name: Optional[str] = None
    ) -> SheetMeta:
        """
        获取表格元数据
        
        Args:
            spreadsheet_token: 表格 token
            sheet_name: Sheet 名称，不指定则获取第一个 sheet
            
        Returns:
            表格元数据
        """
        self.log_info(f"获取表格元数据: token={spreadsheet_token}, sheet={sheet_name}")
        
        # 使用 asyncio 在异步上下文中调用同步方法
        loop = asyncio.get_event_loop()
        
        try:
            # 调用飞书客户端获取 sheets 列表
            response = await loop.run_in_executor(
                None,
                self.feishu_client.list_sheets,
                spreadsheet_token
            )
            
            # 解析响应
            sheets = response.data.sheets if response.data else []
            
            if not sheets:
                raise FeishuAPIError(
                    message="表格中没有找到任何 sheet",
                    code="NO_SHEETS_FOUND",
                    details={"spreadsheet_token": spreadsheet_token}
                )
            
            # 查找指定的 sheet 或返回第一个
            target_sheet = None
            if sheet_name:
                for sheet in sheets:
                    if sheet.title == sheet_name:
                        target_sheet = sheet
                        break
                if not target_sheet:
                    raise FeishuAPIError(
                        message=f"未找到名为 {sheet_name} 的 sheet",
                        code="SHEET_NOT_FOUND",
                        details={"sheet_name": sheet_name, "available_sheets": [s.title for s in sheets]}
                    )
            else:
                target_sheet = sheets[0]
            
            # 解析 grid_properties 以获取行列数（兼容 attr/dict）
            gp = getattr(target_sheet, "grid_properties", None)
            if gp is None and isinstance(target_sheet, dict):
                gp = target_sheet.get("grid_properties")
            rows = 0
            cols = 0
            if gp is not None:
                rows = getattr(gp, "row_count", None)
                cols = getattr(gp, "column_count", None)
                if rows is None and isinstance(gp, dict):
                    rows = gp.get("row_count", 0)
                if cols is None and isinstance(gp, dict):
                    cols = gp.get("column_count", 0)
            
            # 构造 SheetMeta（v3 响应无 revision 字段，置 0）
            return SheetMeta(
                sheet_id=getattr(target_sheet, "sheet_id", ""),
                sheet_name=getattr(target_sheet, "title", ""),
                revision=0,
                last_modified=datetime.now(),  # 飞书 API 可能不返回修改时间
                dimensions={
                    "rows": rows or 0,
                    "cols": cols or 0
                }
            )
            
        except Exception as e:
            if isinstance(e, FeishuAPIError):
                raise
            self._handle_api_error(e)
    
    async def get_sheet_value_range(
        self,
        spreadsheet_token: str,
        range_str: str
    ) -> SheetValueRange:
        """
        获取表格指定范围的数据（返回 SheetValueRange 对象）
        
        Args:
            spreadsheet_token: 表格 token
            range_str: 范围字符串
            
        Returns:
            SheetValueRange 对象
        """
        # 获取原始数据
        raw_data = await self.get_sheet_values(spreadsheet_token, range_str)
        
        # 转换为 SheetValueRange
        return SheetValueRange.from_api_response(raw_data)
    
    def _validate_range(self, range_str: str) -> bool:
        """
        验证范围字符串格式
        
        支持的格式：
        - A1:Z100
        - Sheet1!A1:Z100
        - 'Sheet Name'!A1:Z100
        """
        # 基本的 A1 表示法正则
        # 可选的 sheet 名称（可能带引号）+ ! + 列字母 + 行数字 + : + 列字母 + 行数字
        pattern = r"^(?:(?:'[^']+'|[^!]+)!)?[A-Z]+\d+(?::[A-Z]+\d+)?$"
        return bool(re.match(pattern, range_str))
    
    def _handle_api_error(self, error: Exception) -> None:
        """处理飞书 API 错误"""
        error_msg = str(error)
        
        # 尝试从异常中提取错误码
        error_code = "UNKNOWN"
        if hasattr(error, 'code'):
            error_code = str(error.code)
        elif "code=" in error_msg:
            # 从错误信息中提取
            try:
                error_code = error_msg.split("code=")[1].split(",")[0]
            except:
                pass
        
        self.log_error(f"飞书 API 错误: {error_code} - {error_msg}")
        
        raise FeishuAPIError(
            message=f"飞书 API 调用失败: {error_msg}",
            code=error_code,
            details={"error_msg": error_msg}
        )
