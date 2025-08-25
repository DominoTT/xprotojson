"""
飞书 Drive 服务 - 处理文件夹和文件列表获取
"""
from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime
from app.services.base import BaseService, FeishuAPIError
from app.clients.feishu import FeishuClient
from .models import FileInfo, DriveListResponse


class DriveService(BaseService):
    """飞书 Drive 服务，负责获取文件夹内容"""
    
    def __init__(self, feishu_client: FeishuClient):
        """
        初始化 Drive 服务
        
        Args:
            feishu_client: 飞书客户端实例
        """
        super().__init__("DriveService")
        self.feishu_client = feishu_client
    
    async def list_all_files(
        self, 
        folder_token: str,
        page_size: int = 50
    ) -> List[FileInfo]:
        """
        获取指定文件夹下的所有文件（支持分页）
        
        Args:
            folder_token: 文件夹 token
            page_size: 每页大小
            
        Returns:
            文件信息列表
            
        Raises:
            FeishuAPIError: 飞书 API 调用失败
        """
        self.log_info(f"开始获取文件夹 {folder_token} 下的所有文件")
        
        all_files: List[FileInfo] = []
        page_token: Optional[str] = None
        page_count = 0
        
        while True:
            try:
                # 直接调用 FeishuClient（同步调用）
                response_data = self.feishu_client.list_drive_files(
                    folder_token,
                    page_size,
                    page_token
                )
                
                # 解析响应
                response = self._parse_drive_response(response_data)
                all_files.extend(response.files)
                
                page_count += 1
                self.log_debug(f"获取第 {page_count} 页，文件数: {len(response.files)}")
                
                # 检查是否有更多页
                if not response.has_more or not response.next_page_token:
                    break
                    
                page_token = response.next_page_token
                
                # 避免请求过快
                await asyncio.sleep(0.1)
                
            except Exception as e:
                self._handle_api_error(e)
        
        self.log_info(f"共获取 {len(all_files)} 个文件，分 {page_count} 页")
        self.record_metric("files_fetched", len(all_files))
        self.record_metric("pages_fetched", page_count)
        
        return all_files
    
    async def get_sheets_in_folder(
        self,
        folder_token: str
    ) -> List[FileInfo]:
        """
        获取指定文件夹下的所有表格文件
        
        Args:
            folder_token: 文件夹 token
            
        Returns:
            表格文件信息列表（过滤 type=sheet）
        """
        self.log_info(f"获取文件夹 {folder_token} 下的表格文件")
        
        # 获取所有文件
        all_files = await self.list_all_files(folder_token)
        
        # 过滤表格文件
        sheet_files = [f for f in all_files if f.is_sheet()]
        
        self.log_info(f"找到 {len(sheet_files)} 个表格文件")
        return sheet_files
    

    
    def _parse_drive_response(self, data: Dict[str, Any]) -> DriveListResponse:
        """解析 Drive API 响应"""
        try:
            # 飞书 Drive API 响应格式
            # {
            #   "files": [...],
            #   "has_more": bool,
            #   "next_page_token": str
            # }
            return DriveListResponse.from_api_response(data)
        except Exception as e:
            self.log_error(f"解析 Drive 响应失败: {e}", error=e)
            raise FeishuAPIError(
                message="解析 Drive API 响应失败",
                code="PARSE_ERROR",
                details={"error": str(e), "data": data}
            )
    
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
