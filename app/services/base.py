"""
基础服务类 - 提供通用功能如日志、错误处理、度量等
"""
import logging
from abc import ABC
from typing import Any, Dict, Optional
from datetime import datetime


class BaseService(ABC):
    """所有服务的基类"""
    
    def __init__(self, service_name: str = None):
        """
        初始化基础服务
        
        Args:
            service_name: 服务名称，用于日志标识
        """
        self.service_name = service_name or self.__class__.__name__
        self.logger = logging.getLogger(f"app.services.{self.service_name}")
        self._metrics: Dict[str, Any] = {}
        self._start_time = datetime.now()
    
    def log_info(self, message: str, **kwargs) -> None:
        """记录信息日志"""
        self.logger.info(message, extra=kwargs)
    
    def log_error(self, message: str, error: Optional[Exception] = None, **kwargs) -> None:
        """记录错误日志"""
        self.logger.error(message, exc_info=error, extra=kwargs)
    
    def log_debug(self, message: str, **kwargs) -> None:
        """记录调试日志"""
        self.logger.debug(message, extra=kwargs)
    
    def log_warning(self, message: str, **kwargs) -> None:
        """记录警告日志"""
        self.logger.warning(message, extra=kwargs)
    
    def record_metric(self, metric_name: str, value: Any) -> None:
        """
        记录度量指标
        
        Args:
            metric_name: 指标名称
            value: 指标值
        """
        self._metrics[metric_name] = value
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取所有度量指标"""
        return self._metrics.copy()
    
    def get_uptime_seconds(self) -> float:
        """获取服务运行时长（秒）"""
        return (datetime.now() - self._start_time).total_seconds()


class ServiceException(Exception):
    """服务层异常基类"""
    
    def __init__(self, message: str, code: str = None, details: Dict[str, Any] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConfigNotFoundError(ServiceException):
    """配置未找到异常"""
    pass


class FeishuAPIError(ServiceException):
    """飞书 API 调用异常"""
    pass


class CacheError(ServiceException):
    """缓存操作异常"""
    pass
