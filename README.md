### 项目简介

一个围绕飞书 Lark Sheets 的工具与服务集合：
- **核心库**：最小可用的 `FeishuClient`，基于 `lark-oapi` 实现鉴权、Drive 列表、Sheets 读范围值等；
- **JSON Schema 生成**：从飞书表格表头约定解析出 JSON Schema，并将数据区按 Schema 规范化为对象集合；
- **Manifest 构建**：扫描指定 Drive 文件夹下的文件，生成用于差异化比对的 `manifest.json`；
- **FastAPI 服务**：提供完整的数据 API 服务，支持懒加载缓存、数据合并、类型转换等高级功能。

### 目录结构

```
app/                # FastAPI 应用
  api/v1/
    endpoints/      # API 端点
      health.py     # 健康检查
      test.py       # 测试接口（ping、drive）
      data.py       # 核心数据接口
      demo.py       # 功能演示页面
      simple_demo.py# 简化演示页面
    router.py       # 路由配置
  services/         # 服务层
    structured_service.py  # 结构化数据服务
    cache/          # 缓存服务
    feishu/         # 飞书服务封装
    transform/      # 数据转换
    merge/          # 数据合并
    config_manager.py # 配置管理
  main.py           # FastAPI 入口
python/             # Python 核心库
  core/feishu_client.py         # 飞书客户端封装
  json_schema/feishu_service.py # 从表头生成 JSON Schema & 读取数据
  json_schema/manifest_service.py# 生成 manifest.json
  configs/xpj.feishu.yaml       # 运行所需配置（可从环境变量注入）
config/             # 配置文件
  sheet_configs.json # 表格配置定义
sample/             # 示例与附加资源
```

### 快速开始

1) 安装依赖（建议 Python 3.10+）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
pip install -r python/requirements.txt
```

2) 配置凭证（任选其一）

- 环境变量：

```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
```

- 或编辑文件 `python/configs/xpj.feishu.yaml`：

```yaml
auth:
  app_id: "your_app_id"
  app_secret: "your_app_secret"
```

3) 启动服务

```bash
uvicorn app.main:app --reload
```

4) 访问服务

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health
- 功能演示：http://127.0.0.1:8000/api/v1/demo/
- 简化演示：http://127.0.0.1:8000/api/v1/demo/simple

### 库用法示例

确保将项目根目录加入 `PYTHONPATH`：

```bash
export PYTHONPATH=$PWD:$PYTHONPATH
```

读取表头生成 JSON Schema，并按约定读取数据：

```python
from python.core.feishu_client import FeishuClient
from python.json_schema.feishu_service import FeishuSchemaService

client = FeishuClient()
svc = FeishuSchemaService(client)

schema = svc.build_schema_for_spreadsheet(
    spreadsheet_token="your_spreadsheet_token",
    sheet_id="your_sheet_id",
)

items = svc.build_items_for_sheet(
    spreadsheet_token="your_spreadsheet_token",
    sheet_id="your_sheet_id",
)
print(schema)
print(items)
```

构建某个 Drive 文件夹的清单 `manifest.json`：

```python
from python.core.feishu_client import FeishuClient
from python.json_schema.manifest_service import ManifestService

client = FeishuClient()
manifest = ManifestService(client, output_dir="./out").build_manifest_for_folder(
    folder_token="your_folder_token"
)
print(manifest)
```

### FastAPI 数据服务

#### 核心功能

- **智能数据转换**：自动将飞书表格转换为结构化 JSON，支持类型推断和数组/JSON 列解析
- **懒加载缓存**：首次请求时获取数据并缓存，后续请求直接返回缓存，支持强制刷新
- **数据合并**：自动识别并合并相关表格（如 `Config_Unit(hero)` + `Config_Unit(soldier)`）
- **高性能 API**：基于 FastAPI + Redis，支持异步处理和分布式缓存

#### 主要 API 端点

**数据接口** (`/api/v1/data/`)

- `GET /sheets/{sheet_name}` - 获取表格数据
  - 参数：`force_refresh=false` - 是否强制刷新缓存
  - 示例：`/api/v1/data/sheets/Config_Unit(hero)`

- `GET /groups/{group_name}` - 获取组合并数据
  - 自动合并同组下的所有表格
  - 示例：`/api/v1/data/groups/Config_Unit`

- `GET /configs` - 获取配置信息
  - 查看所有已配置的表格和组信息

- `GET /cache/stats` - 获取缓存统计
  - 查看缓存使用统计信息

- `POST /sheets/{sheet_name}/refresh` - 刷新表格数据
  - 强制刷新指定表格的缓存数据

- `DELETE /cache` - 清理缓存
  - 参数：`pattern=xpj:*` - 缓存键模式匹配

**测试接口** (`/api/v1/test/`)

- `GET /ping` - 基础连通性测试
- `GET /page` - 测试页面信息  
- `GET /drive` - 测试飞书目录列表
  - 参数：`folder_token`, `page_size`, `page_token`

**演示页面** (`/api/v1/demo/`)

- `GET /` - 功能演示主页（包含可交互的 API 测试）
- `GET /simple` - 简化演示页面（不依赖 Redis）
- `GET /status` - 系统状态信息

#### 数据响应格式

```json
{
  "success": true,
  "data": {
    "key1": {"field1": "value1", "field2": 123},
    "key2": {"field1": "value2", "field2": 456}
  },
  "message": "成功获取表格数据",
  "metadata": {
    "total_count": 2,
    "cache_hit": true,
    "last_updated": "2024-01-01T12:00:00"
  }
}
```

#### 使用示例

```bash
# 获取英雄数据
curl "http://localhost:8000/api/v1/data/sheets/Config_Unit(hero)"

# 获取合并的单位组数据
curl "http://localhost:8000/api/v1/data/groups/Config_Unit"

# 强制刷新缓存
curl "http://localhost:8000/api/v1/data/sheets/Config_Skill?force_refresh=true"

# 刷新特定表格
curl -X POST "http://localhost:8000/api/v1/data/sheets/Config_Unit(hero)/refresh"

# 查看缓存统计
curl "http://localhost:8000/api/v1/data/cache/stats"
```

### Roadmap（后续计划）

- JSON ↔ 飞书表格互转
  - 从 JSON/JSON Schema 生成飞书表格（字段、类型、注释）
  - 从飞书表格批量导出/更新 JSON（含类型、可选项校验）
- 提供 MCP/AI Agent 服务
  - 基于 FastAPI 封装为 MCP 兼容服务，暴露“表格读取/写入、Schema 生成、清单同步”等能力
  - 集成 Agent（如函数调用/工具插件）驱动飞书数据读写与校验
- 增强的配置与缓存
  - 支持多环境与多租户配置；磁盘/Redis 缓存 Schema 与数据片段
- 任务编排与增量同步
  - 根据 `manifest.json` 做差异比对与增量同步；支持定时/回调触发
- Web UI
  - 提供简单的可视化来预览 Schema、数据与同步计划

### 许可

可自由用于学习与内部项目，生产使用前请完善鉴权、审计与异常处理。

