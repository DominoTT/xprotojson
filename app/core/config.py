from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeishuAuthSettings(BaseModel):
	"""Feishu 应用鉴权配置。"""
	app_id: Optional[str] = Field(default=None, description="Feishu App ID")
	app_secret: Optional[str] = Field(default=None, description="Feishu App Secret")
	verification_token: Optional[str] = Field(
		default=None, description="事件订阅 Verification Token"
	)
	encrypt_key: Optional[str] = Field(
		default=None, description="事件订阅 Encrypt Key"
	)
	tenant_key: Optional[str] = Field(
		default=None, description="可选：租户 Key（部分场景使用）"
	)


class FeishuSettings(BaseModel):
	"""Feishu 相关配置。支持嵌套环境变量：
	- XPJ_FEISHU__AUTH__APP_ID
	- XPJ_FEISHU__AUTH__APP_SECRET
	- XPJ_FEISHU__AUTH__VERIFICATION_TOKEN
	- XPJ_FEISHU__AUTH__ENCRYPT_KEY
	- XPJ_FEISHU__AUTH__TENANT_KEY
	- XPJ_FEISHU__BASE_URL
	- XPJ_FEISHU__TIMEOUT_SECONDS
	"""

	auth: FeishuAuthSettings = Field(default_factory=FeishuAuthSettings)
	base_url: str = Field(
		default="https://open.feishu.cn", description="Feishu OpenAPI Base URL"
	)
	timeout_seconds: int = Field(
		default=10, ge=1, le=120, description="HTTP 请求超时时间（秒）"
	)


class RedisSettings(BaseModel):
	"""Redis 基础配置。优先使用 `url`，否则拼装分段配置。支持：
	- XPJ_REDIS__URL
	- XPJ_REDIS__HOST / PORT / DB / USERNAME / PASSWORD / SSL
	"""

	url: Optional[str] = Field(default=None, description="Redis 连接 URL，优先使用")
	host: str = Field(default="127.0.0.1", description="Redis 主机")
	port: int = Field(default=6379, ge=1, le=65535, description="Redis 端口")
	db: int = Field(default=0, ge=0, description="Redis DB 索引")
	username: Optional[str] = Field(default=None, description="用户名，可选")
	password: Optional[str] = Field(default=None, description="密码，可选")
	ssl: bool = Field(default=False, description="是否启用 SSL")

	@property
	def dsn(self) -> str:
		if self.url:
			return self.url
		scheme = "rediss" if self.ssl else "redis"
		# 用户名密码
		auth_part = ""
		if self.username and self.password:
			auth_part = f"{self.username}:{self.password}@"
		elif self.password and not self.username:
			auth_part = f":{self.password}@"
		return f"{scheme}://{auth_part}{self.host}:{self.port}/{self.db}"


class TableConfig(BaseModel):
	"""表格配置：支持列表或映射形式的表头。
	- XPJ_TABLE__HEADERS：JSON（["A","B"]）或逗号分隔（"A,B"）
	- XPJ_TABLE__HEADER_MAP：JSON（{"key":"列名"}）
	"""

	headers: List[str] = Field(default_factory=list, description="表头列表")
	header_map: Dict[str, str] = Field(
		default_factory=dict, description="字段到列名的映射，可选"
	)
	# 0-based 行索引配置
	index_row: int = Field(default=0, ge=0, description="索引行（通常为自增序号）")
	header_name_row: int = Field(default=1, ge=0, description="列名所在行（用作 JSON 属性名）")
	type_row: int = Field(default=2, ge=0, description="类型所在行（int/float/bool/str/array/json）")
	comment_row: int = Field(default=3, ge=0, description="备注所在行（可选，不参与解析）")
	data_start_row: int = Field(default=4, ge=0, description="数据开始行（0-based）")
	default_key_column: str = Field(default="ID", description="默认主键列名")

	@field_validator("headers", mode="before")
	@classmethod
	def _parse_headers(cls, v):
		if v is None:
			return []
		if isinstance(v, list):
			return v
		if isinstance(v, str):
			# 优先尝试 JSON
			val = v.strip()
			if val.startswith("[") and val.endswith("]"):
				try:
					import json
					return json.loads(val)
				except Exception:
					pass
			# 退化为逗号分隔
			return [item.strip() for item in val.split(",") if item.strip()]
		return v


class FolderSettings(BaseModel):
	"""文件夹配置。支持环境变量：
	- XPJ_FOLDERS__DEFAULT
	- XPJ_FOLDERS__CONFIG
	- XPJ_FOLDERS__TEST
	"""
	default: str = Field(default="fldcnVaJ6ltyVOJOHXtl6Ug6nOc", description="默认文件夹 token")
	config: str = Field(default="fldcnVaJ6ltyVOJOHXtl6Ug6nOc", description="配置文件夹 token")
	test: str = Field(default="fldcnVaJ6ltyVOJOHXtl6Ug6nOc", description="测试文件夹 token")


class Settings(BaseSettings):

	app_name: str = "XProtoJSON API"
	debug: bool = True
	reload: bool = True
	host: str = "127.0.0.1"
	port: int = 8000

	# 嵌套配置
	feishu: FeishuSettings = Field(default_factory=FeishuSettings)
	redis: RedisSettings = Field(default_factory=RedisSettings)
	table: TableConfig = Field(default_factory=TableConfig)
	folders: FolderSettings = Field(default_factory=FolderSettings)

	model_config = SettingsConfigDict(
		env_prefix="XPJ_",
		case_sensitive=False,
		env_nested_delimiter="__",
		env_file=".env",
		env_file_encoding="utf-8",
	)


settings = Settings()
