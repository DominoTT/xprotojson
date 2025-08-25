# 分组索引示例

## 移除 tgroup 后的 Redis 键结构

### 原来的结构（有 tgroup 中间层）
```
xpj:gids:Config_Unit_Basic:tgroup:Group测试
xpj:gids:Config_Unit_Basic:Subtype:hero
xpj:gcount:Config_Unit_Basic:tgroup
xpj:gcount:Config_Unit_Basic:Subtype
```

### 现在的结构（直接使用分组名）
```
xpj:gids:Config_Unit_Basic:Subtype:hero
xpj:gids:Config_Unit_Basic:Subtype:soldier
xpj:gcount:Config_Unit_Basic:Subtype
xpj:gstate:Config_Unit_Basic:11001 = {"Subtype": "hero"}
```

## 数据示例

假设有表格 `Config_Unit_Basic(Group测试)` 包含以下数据：

| ID | Name | Subtype | Level |
|----|------|---------|-------|
| 11001 | 英雄A | hero | 10 |
| 11002 | 英雄B | hero | 15 |
| 21001 | 士兵A | soldier | 5 |

### Redis 中的索引结构

1. **全表 ID 索引**：
   ```
   xpj:ids:Config_Unit_Basic = {11001, 11002, 21001}
   ```

2. **分组 ID 索引**：
   ```
   xpj:gids:Config_Unit_Basic:Subtype:hero = {11001, 11002}
   xpj:gids:Config_Unit_Basic:Subtype:soldier = {21001}
   ```

3. **分组计数**：
   ```
   xpj:gcount:Config_Unit_Basic:Subtype = {"hero": 2, "soldier": 1}
   ```

4. **行分组状态**：
   ```
   xpj:gstate:Config_Unit_Basic:11001 = {"Subtype": "hero"}
   xpj:gstate:Config_Unit_Basic:11002 = {"Subtype": "hero"}
   xpj:gstate:Config_Unit_Basic:21001 = {"Subtype": "soldier"}
   ```

## 查询示例

1. **获取所有 hero 类型的 ID**：
   ```
   GET /api/v1/data/tables/Config_Unit_Basic/groups/Subtype/values/hero/ids
   ```

2. **获取 Subtype 分组的计数**：
   ```
   GET /api/v1/data/tables/Config_Unit_Basic/groups/Subtype/counts
   ```

## 优势

1. **简化结构**：移除了 tgroup 中间层，直接使用业务分组
2. **减少存储**：不再为每行存储重复的表级分组信息
3. **概念清晰**：只有一种分组概念（业务分组），避免混淆
4. **查询直观**：API 路径直接对应业务分组字段
