"""
服务依赖注入模块
"""
from typing import Annotated
from fastapi import Depends, Request

from app.services.feishu import DriveService, SheetService
from app.services.cache import RedisService
from app.services.transform import SheetTransformer
from app.services.merge import SheetMerger
from app.clients.feishu import FeishuClient
from app.services.sheet_sync_service import SheetSyncService
from app.services.index_builder import IndexBuilder


# 全局服务实例
_redis_service = None
_transformer = None
_merger = None
_sheet_sync_service = None
_index_builder = None


def get_feishu_client(request: Request) -> FeishuClient:
    """获取 FeishuClient"""
    return request.app.state.feishu





def get_redis_service() -> RedisService:
    """获取 Redis 服务"""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service


def get_index_builder() -> IndexBuilder:
    """获取索引构建服务"""
    global _index_builder
    if _index_builder is None:
        _index_builder = IndexBuilder(get_redis_service())
    return _index_builder


def get_transformer() -> SheetTransformer:
    """获取数据转换器"""
    global _transformer
    if _transformer is None:
        _transformer = SheetTransformer()
    return _transformer


def get_merger() -> SheetMerger:
    """获取合并器"""
    global _merger
    if _merger is None:
        _merger = SheetMerger()
    return _merger


def get_drive_service(feishu_client: Annotated[FeishuClient, Depends(get_feishu_client)]) -> DriveService:
    """获取 Drive 服务"""
    return DriveService(feishu_client)


def get_sheet_service(feishu_client: Annotated[FeishuClient, Depends(get_feishu_client)]) -> SheetService:
    """获取 Sheet 服务"""
    return SheetService(feishu_client)


# 结构化服务已下线：相关依赖与路由已移除


def get_sheet_sync_service(
    sheet_service: Annotated[SheetService, Depends(get_sheet_service)],
    redis_service: Annotated[RedisService, Depends(get_redis_service)],
    transformer: Annotated[SheetTransformer, Depends(get_transformer)],
) -> SheetSyncService:
    """获取 Sheet 同步服务"""
    global _sheet_sync_service
    if _sheet_sync_service is None:
        _sheet_sync_service = SheetSyncService(
            sheet_service=sheet_service,
            redis_service=redis_service,
            transformer=transformer,
        )
    return _sheet_sync_service




# 类型别名，方便在端点中使用
FeishuClientDep = Annotated[FeishuClient, Depends(get_feishu_client)]

RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]
SheetTransformerDep = Annotated[SheetTransformer, Depends(get_transformer)]
SheetMergerDep = Annotated[SheetMerger, Depends(get_merger)]
DriveServiceDep = Annotated[DriveService, Depends(get_drive_service)]
SheetServiceDep = Annotated[SheetService, Depends(get_sheet_service)]
SheetSyncServiceDep = Annotated[SheetSyncService, Depends(get_sheet_sync_service)]
IndexBuilderDep = Annotated[IndexBuilder, Depends(get_index_builder)]
