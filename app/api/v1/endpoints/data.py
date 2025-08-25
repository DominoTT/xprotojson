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


class DataQueryResponse(BaseModel):
    """数据查询响应"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: str = ""
    metadata: Optional[Dict[str, Any]] = None



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


@router.get("/by-id", response_model=DataQueryResponse, summary="根据 ID 查询单条数据")
async def get_data_by_id(
    id: int = Query(..., description="数据 ID"),
    redis_service: RedisServiceDep = None,
) -> DataQueryResponse:
    """根据 ID 查询 Redis 中 cfgid 对应的 JSON 数据"""
    try:
        # 构造 cfgid 键
        cfgid_key = CacheKeys.row_cfgid_key(str(id))
        
        # 从 Redis 获取数据
        data = await redis_service.get(cfgid_key)
        
        if data is None:
            return DataQueryResponse(
                success=False,
                message=f"未找到 ID {id} 对应的数据",
                metadata={"id": id, "key": cfgid_key}
            )
        
        # 确保返回的是字典格式的 JSON 数据
        if not isinstance(data, dict):
            return DataQueryResponse(
                success=False,
                message=f"数据格式错误，期望 JSON 对象",
                metadata={"id": id, "data_type": type(data).__name__}
            )
        
        # 构造元数据
        metadata = {
            "id": id,
            "key": cfgid_key,
        }
        
        # 如果数据包含表信息，添加到元数据
        if "_table" in data:
            metadata["table"] = data["_table"]
            
        # 添加分组信息
        if "_group" in data:
            metadata["group"] = data["_group"]
        
        return DataQueryResponse(
            success=True,
            data=data,
            message="查询成功",
            metadata=metadata
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/by-ids", response_model=DataResponse, summary="批量查询多个 ID 的数据")
async def get_data_by_ids(
    ids: str = Query(..., description="ID 列表，逗号分隔，如: 1001,1002,1003"),
    redis_service: RedisServiceDep = None,
) -> DataResponse:
    """批量根据 ID 查询 Redis 中 cfgid 对应的 JSON 数据"""
    try:
        # 解析 ID 列表
        try:
            id_list = [int(id_str.strip()) for id_str in ids.split(",") if id_str.strip()]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"ID 格式错误: {str(e)}")
        
        if not id_list:
            raise HTTPException(status_code=400, detail="ID 列表不能为空")
        
        if len(id_list) > 100:
            raise HTTPException(status_code=400, detail="批量查询 ID 数量不能超过 100")
        
        # 构造所有 cfgid 键
        keys = [CacheKeys.row_cfgid_key(str(id)) for id in id_list]
        
        # 批量获取数据
        results = await redis_service.mget(keys)
        
        # 构造响应数据
        data = {}
        found_count = 0
        
        for id, result in zip(id_list, results):
            if result is not None and isinstance(result, dict):
                data[str(id)] = result
                found_count += 1
        
        return DataResponse(
            success=True,
            data=data,
            message=f"查询完成，找到 {found_count}/{len(id_list)} 条数据",
            metadata={
                "requested_ids": id_list,
                "found_count": found_count,
                "total_requested": len(id_list)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量查询失败: {str(e)}")


@router.get("/by-table", response_model=DataResponse, summary="根据表格名查询该表的所有数据")
async def get_data_by_table(
    table: str = Query(..., description="表格名称"),
    offset: int = Query(0, description="偏移量，用于分页", ge=0),
    limit: int = Query(100, description="返回数据条数限制", ge=1, le=1000),
    redis_service: RedisServiceDep = None,
    index_builder: IndexBuilderDep = None,
) -> DataResponse:
    """根据表格名查询该表的所有数据，支持分页"""
    try:
        # 获取表的所有 ID（分页）
        ids = await index_builder.ids_range(table, offset, offset + limit - 1)
        
        if not ids:
            return DataResponse(
                success=True,
                data={},
                message=f"表 {table} 中没有找到数据（偏移量: {offset}）",
                metadata={
                    "table": table,
                    "offset": offset,
                    "limit": limit,
                    "total_found": 0
                }
            )
        
        # 构造所有 cfgid 键
        keys = [CacheKeys.row_cfgid_key(str(id)) for id in ids]
        
        # 批量获取数据
        results = await redis_service.mget(keys)
        
        # 构造响应数据，只包含属于指定表的数据
        data = {}
        found_count = 0
        
        for id, result in zip(ids, results):
            if result is not None and isinstance(result, dict):
                # 验证数据确实属于指定表
                if result.get("_table") == table:
                    data[str(id)] = result
                    found_count += 1
        
        # 获取总数量（用于分页信息）
        total_count = await index_builder.ids_count(table)
        
        return DataResponse(
            success=True,
            data=data,
            message=f"查询完成，返回 {found_count} 条数据",
            metadata={
                "table": table,
                "offset": offset,
                "limit": limit,
                "returned_count": found_count,
                "total_count": total_count,
                "has_more": offset + limit < total_count
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"按表查询失败: {str(e)}")
