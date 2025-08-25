"""
Sheet 合并器 - 执行多个 Sheet 的合并操作
"""
from typing import Dict, List, Any, Callable, Awaitable, Optional
import asyncio

from app.services.base import BaseService
from app.services.transform.schema import SheetConfig
from .rules import MergeRule, MergeRuleManager


class SheetMerger(BaseService):
    """Sheet 数据合并器"""
    
    def __init__(self, rule_manager: Optional[MergeRuleManager] = None):
        super().__init__("SheetMerger")
        self.rule_manager = rule_manager or MergeRuleManager()
    
    async def merge_group(
        self,
        group_name: str,
        configs: List[SheetConfig],
        fetch_structured: Callable[[str], Awaitable[Dict[str, Dict[str, Any]]]],
        merge_rule: Optional[MergeRule] = None
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        合并同组的多个 Sheet
        
        Args:
            group_name: 组名
            configs: 该组的所有 Sheet 配置
            fetch_structured: 获取结构化数据的函数
            merge_rule: 合并规则（不提供则使用默认规则）
            
        Returns:
            合并后的数据
            {
                "hero": {"11001": {...}, "11002": {...}},
                "soldier": {"21001": {...}, "21002": {...}}
            }
        """
        self.log_info(f"开始合并组 {group_name}，包含 {len(configs)} 个表格")
        
        # 获取合并规则
        if merge_rule is None:
            merge_rule = self.rule_manager.get_rule_for_group(group_name)
        
        # 结果容器
        result = {}
        
        # 用于检测主键冲突
        key_source_map = {}  # {key: (sub_type, data)}
        
        # 并发获取所有 sheet 的数据
        tasks = []
        for config in configs:
            tasks.append(self._fetch_sheet_data(config, fetch_structured))
        
        # 等待所有数据获取完成
        sheet_data_list = await asyncio.gather(*tasks)
        
        # 合并数据
        for config, sheet_data in zip(configs, sheet_data_list):
            if sheet_data is None:
                continue
                
            sub_type = config.sub_type or "default"
            
            # 初始化子类型容器
            if sub_type not in result:
                result[sub_type] = {}
            
            # 合并数据并检查冲突
            for key, row_data in sheet_data.items():
                if key in key_source_map:
                    # 处理主键冲突
                    existing_sub_type, existing_data = key_source_map[key]
                    if existing_sub_type != sub_type:
                        self.log_warning(
                            f"主键冲突: {key} 同时存在于 {existing_sub_type} 和 {sub_type}"
                        )
                        # 根据策略处理冲突
                        resolved_data = self._resolve_conflict(
                            key=key,
                            existing_data=existing_data,
                            existing_sub_type=existing_sub_type,
                            new_data=row_data,
                            new_sub_type=sub_type,
                            strategy=merge_rule.conflict_strategy
                        )
                        if resolved_data:
                            result[sub_type][key] = resolved_data
                    else:
                        # 同一子类型内的重复，根据策略合并
                        merged = self._merge_data_with_strategy(
                            existing_data,
                            row_data,
                            merge_rule.conflict_strategy
                        )
                        result[sub_type][key] = merged
                        key_source_map[key] = (sub_type, merged)
                else:
                    # 新键，直接添加
                    result[sub_type][key] = row_data
                    key_source_map[key] = (sub_type, row_data)
        
        # 记录统计信息
        total_rows = sum(len(data) for data in result.values())
        self.log_info(
            f"合并完成: {len(result)} 个子类型，共 {total_rows} 条数据"
        )
        self.record_metric("merged_subtypes", len(result))
        self.record_metric("merged_rows", total_rows)
        
        return result
    
    async def _fetch_sheet_data(
        self,
        config: SheetConfig,
        fetch_structured: Callable[[str], Awaitable[Dict[str, Dict[str, Any]]]]
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """获取单个 sheet 的数据"""
        try:
            data = await fetch_structured(config.sheet_name)
            self.log_info(f"获取 {config.sheet_name} 数据成功，共 {len(data)} 条")
            return data
        except Exception as e:
            self.log_error(f"获取 {config.sheet_name} 数据失败: {e}", error=e)
            return None
    
    def _merge_data_with_strategy(
        self,
        existing_data: Dict[str, Any],
        new_data: Dict[str, Any],
        strategy: str
    ) -> Dict[str, Any]:
        """
        根据策略合并数据
        
        Args:
            existing_data: 已存在的数据
            new_data: 新数据
            strategy: 合并策略
            
        Returns:
            合并后的数据
        """
        if strategy == "last_win":
            # 新数据覆盖
            return new_data
        
        elif strategy == "first_win":
            # 保留原数据
            return existing_data
        
        elif strategy == "merge_fields":
            # 字段级合并
            result = existing_data.copy()
            for field, value in new_data.items():
                if field not in result or result[field] is None:
                    result[field] = value
                elif value is not None:
                    # 如果都有值，可能需要更复杂的合并逻辑
                    # 这里简单处理：数组合并，其他覆盖
                    if isinstance(result[field], list) and isinstance(value, list):
                        # 合并数组（去重）
                        merged_list = result[field] + value
                        result[field] = list(dict.fromkeys(merged_list))
                    else:
                        # 其他类型直接覆盖
                        result[field] = value
            return result
        
        else:
            # 默认策略：覆盖
            self.log_warning(f"未知的合并策略: {strategy}，使用默认覆盖策略")
            return new_data
    
    def _resolve_conflict(
        self,
        key: str,
        existing_data: Dict[str, Any],
        existing_sub_type: str,
        new_data: Dict[str, Any],
        new_sub_type: str,
        strategy: str
    ) -> Optional[Dict[str, Any]]:
        """
        解决跨子类型的主键冲突
        
        Args:
            key: 冲突的主键
            existing_data: 已存在的数据
            existing_sub_type: 已存在数据的子类型
            new_data: 新数据
            new_sub_type: 新数据的子类型
            strategy: 冲突策略
            
        Returns:
            解决后的数据，None 表示跳过
        """
        self.log_info(
            f"解决主键冲突: {key} ({existing_sub_type} vs {new_sub_type})"
        )
        
        # 根据子类型优先级或其他业务规则处理
        # 这里简单实现：按子类型字母顺序，后者覆盖前者
        if strategy == "last_win":
            return new_data
        elif strategy == "first_win":
            return None  # 保留原有数据，跳过新数据
        else:
            # 可以根据具体业务逻辑添加更复杂的规则
            # 例如：英雄数据优先于士兵数据
            if existing_sub_type == "hero" and new_sub_type == "soldier":
                return None  # 英雄优先，跳过士兵数据
            elif existing_sub_type == "soldier" and new_sub_type == "hero":
                return new_data  # 英雄优先，覆盖士兵数据
            else:
                # 默认后来者覆盖
                return new_data
    
    def merge_flat(
        self,
        sheets_data: Dict[str, Dict[str, Dict[str, Any]]],
        merge_rule: Optional[MergeRule] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        将分组数据平铺合并（不保留子类型结构）
        
        Args:
            sheets_data: 分组数据 {sub_type: {key: data}}
            merge_rule: 合并规则
            
        Returns:
            平铺的数据 {key: data}
        """
        if merge_rule is None:
            merge_rule = MergeRule(pattern="")
        
        result = {}
        
        # 按子类型顺序处理（可配置优先级）
        for sub_type in sorted(sheets_data.keys()):
            for key, data in sheets_data[sub_type].items():
                if key in result:
                    # 合并冲突
                    result[key] = self._merge_data_with_strategy(
                        result[key],
                        data,
                        merge_rule.conflict_strategy
                    )
                else:
                    result[key] = data
        
        return result
