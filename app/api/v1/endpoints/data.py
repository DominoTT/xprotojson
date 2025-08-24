"""
数据 API 端点
"""
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
from app.services.dependencies import (
    RedisServiceDep,
    SheetSyncServiceDep,
    IndexBuilderDep,
    DriveServiceDep,
)
from app.services.cache import CacheKeys
from app.core.config import settings

router = APIRouter()


class DataResponse(BaseModel):
    """统一的数据响应格式"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: str = ""
    metadata: Optional[Dict[str, Any]] = None


class CacheStatsResponse(BaseModel):
    """缓存统计响应"""
    total_keys: int
    sheet_keys: int
    group_keys: int
    folder_keys: int


class SyncResponse(BaseModel):
    """同步响应"""
    success: bool
    message: str = ""
    details: Optional[Dict[str, Any]] = None


class IdListResponse(BaseModel):
    total: int
    ids: List[int]


class GroupCountResponse(BaseModel):
    group: str
    counts: Dict[str, int]


class FolderSyncResponse(BaseModel):
    """文件夹同步响应"""
    success: bool
    message: str = ""
    folder_token: str
    total_sheets: int
    synced_sheets: int
    failed_sheets: int
    details: List[Dict[str, Any]] = []


class FolderListResponse(BaseModel):
    """文件夹内容响应"""
    folder_token: str
    total_sheets: int
    sheets: List[Dict[str, Any]] = []



@router.post("/sheets/{sheet_token}/sync", response_model=SyncResponse, summary="同步指定表格到 Redis")
async def sync_sheet_to_redis(
    sheet_token: str = Path(..., description="飞书 spreadsheet token"),
    sync_service: SheetSyncServiceDep = None,
) -> SyncResponse:
    try:
        result = await sync_service.sync_sheet(sheet_token)
        return SyncResponse(success=True, message="同步完成", details=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/folders/{folder_token}/sync", response_model=FolderSyncResponse, summary="同步指定文件夹下的所有表格")
async def sync_folder_sheets(
    folder_token: str = Path(..., description="飞书文件夹 token"),
    drive_service: DriveServiceDep = None,
    sync_service: SheetSyncServiceDep = None,
) -> FolderSyncResponse:
    """同步指定文件夹下的所有 spreadsheet 到 Redis"""
    try:
        
        # 获取文件夹下的所有表格文件
        sheet_files = await drive_service.get_sheets_in_folder(folder_token)
        
        total_sheets = len(sheet_files)
        synced_sheets = 0
        failed_sheets = 0
        details = []
        
        # 逐个同步表格
        for sheet_file in sheet_files:
            try:
                # 使用文件 token 作为 spreadsheet token 进行同步
                result = await sync_service.sync_sheet(sheet_file.token)
                synced_sheets += 1
                details.append({
                    "file_name": sheet_file.name,
                    "file_token": sheet_file.token,
                    "status": "success",
                    "rows_written": result.get("total_rows_written", 0),
                    "sheets_count": len(result.get("sheets", []))
                })
            except Exception as e:
                failed_sheets += 1
                details.append({
                    "file_name": sheet_file.name,
                    "file_token": sheet_file.token,
                    "status": "failed",
                    "error": str(e)
                })
        
        success = failed_sheets == 0
        message = f"同步完成: {synced_sheets}/{total_sheets} 成功"
        if failed_sheets > 0:
            message += f", {failed_sheets} 失败"
        
        return FolderSyncResponse(
            success=success,
            message=message,
            folder_token=folder_token,
            total_sheets=total_sheets,
            synced_sheets=synced_sheets,
            failed_sheets=failed_sheets,
            details=details
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件夹同步失败: {str(e)}")


@router.post("/folders/sync", response_model=FolderSyncResponse, summary="同步默认文件夹下的所有表格")
async def sync_default_folder_sheets(
    drive_service: DriveServiceDep = None,
    sync_service: SheetSyncServiceDep = None,
) -> FolderSyncResponse:
    """同步默认文件夹下的所有 spreadsheet 到 Redis"""
    return await sync_folder_sheets(settings.folders.default, drive_service, sync_service)
