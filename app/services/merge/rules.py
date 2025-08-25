"""
合并规则定义 - 识别组名和子类型
"""
import re
from typing import Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class MergeRule:
    """合并规则配置"""
    pattern: str  # 正则表达式模式
    priority: int = 0  # 优先级（数字越大优先级越高）
    conflict_strategy: str = "last_win"  # 冲突策略: last_win, first_win, merge_fields


def identify_group_and_sub(sheet_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    识别 Sheet 的组名和子类型
    
    Args:
        sheet_name: Sheet 名称，如 "Config_Unit(hero)"
        
    Returns:
        (group_name, sub_type) 元组
        例如: ("Config_Unit", "hero")
        如果不匹配返回 (None, None)
    """
    # 模式1: Config_XXX(sub_type) - 最常见模式
    pattern1 = r'^(?P<group>Config_[A-Za-z0-9_]+)\((?P<sub>[^)]+)\)$'
    match = re.match(pattern1, sheet_name)
    if match:
        return match.group('group'), match.group('sub')
    
    # 模式2: Config_XXX_sub_type - 下划线分隔
    pattern2 = r'^(?P<group>Config_[A-Za-z0-9]+)_(?P<sub>[a-z]+)$'
    match = re.match(pattern2, sheet_name)
    if match:
        return match.group('group'), match.group('sub')
    
    # 模式3: Config_XXX[sub_type] - 方括号模式
    pattern3 = r'^(?P<group>Config_[A-Za-z0-9_]+)\[(?P<sub>[^\]]+)\]$'
    match = re.match(pattern3, sheet_name)
    if match:
        return match.group('group'), match.group('sub')
    
    # 不匹配任何模式，返回整个名称作为组名
    if sheet_name.startswith("Config_"):
        return sheet_name, None
    
    return None, None


class MergeRuleManager:
    """合并规则管理器"""
    
    def __init__(self):
        self.rules: Dict[str, MergeRule] = {
            "default": MergeRule(
                pattern=r'^(?P<group>Config_[A-Za-z0-9_]+)\((?P<sub>[^)]+)\)$',
                priority=0,
                conflict_strategy="last_win"
            )
        }
    
    def add_rule(self, name: str, rule: MergeRule) -> None:
        """添加合并规则"""
        self.rules[name] = rule
    
    def get_rule_for_group(self, group_name: str) -> MergeRule:
        """获取指定组的合并规则"""
        # TODO: 根据组名返回对应规则
        return self.rules.get("default")
