import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import lark_oapi as lark
from lark_oapi.api.sheets.v3 import (
	QuerySpreadsheetSheetRequest,
	QuerySpreadsheetSheetResponse,
)

from app.core.config import settings


class FeishuClient:
	"""
	最小实现：鉴权 + Sheets/Drive 常用调用。
	凭据来自 `settings.feishu.auth`，若缺失将抛出异常。
	"""

	def __init__(
		self,
		app_id: Optional[str] = None,
		app_secret: Optional[str] = None,
		log_level: lark.LogLevel = lark.LogLevel.DEBUG,
	) -> None:
		self._logger = logging.getLogger("xpj.feishu")
		cid = app_id or settings.feishu.auth.app_id
		csecret = app_secret or settings.feishu.auth.app_secret
		if not cid or not csecret:
			raise ValueError("Feishu credentials missing: configure XPJ_FEISHU__AUTH__APP_ID/APP_SECRET")
		self.client = (
			lark.Client.builder()
			.app_id(cid)
			.app_secret(csecret)
			.log_level(log_level)
			.build()
		)

	# ---------- Drive v1：列出指定文件夹下的文件（单页） ----------
	def list_drive_files(
		self,
		folder_token: str,
		page_size: int = 50,
		page_token: Optional[str] = None,
		order_by: str = "EditedTime",
		direction: str = "DESC",
		user_id_type: str = "open_id",
	) -> Dict[str, Any]:
		try:
			from lark_oapi.api.drive.v1 import ListFileRequest, ListFileResponse
		except ModuleNotFoundError as e:
			raise NotImplementedError(
				"当前 lark-oapi 版本未提供 drive.v1 file.list API。请升级到 >=1.4.15。"
			) from e

		builder = (
			ListFileRequest.builder()
			.page_size(page_size)
			.folder_token(folder_token)
			.order_by(order_by)
			.direction(direction)
			.user_id_type(user_id_type)
		)
		if page_token:
			builder = builder.page_token(page_token)
		request = builder.build()

		response: ListFileResponse = self.client.drive.v1.file.list(request)
		if not response.success():
			self._logger.error(
				f"client.drive.v1.file.list failed, code: {response.code}, msg: {response.msg}, "
				f"log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
			)
			raise RuntimeError(f"Drive list failed: {response.code} {response.msg}")

		return response.data if response.data is not None else {}

	# ---------- Sheets v3：列出工作表（返回原生响应对象） ----------
	def list_sheets(self, spreadsheet_token: str):
		request: QuerySpreadsheetSheetRequest = (
			QuerySpreadsheetSheetRequest.builder()
			.spreadsheet_token(spreadsheet_token)
			.build()
		)
		response: QuerySpreadsheetSheetResponse = (
			self.client.sheets.v3.spreadsheet_sheet.query(request)
		)
		if not response.success():
			self._logger.error(
				f"client.sheets.v3.spreadsheet_sheet.query failed, code: {response.code}, msg: {response.msg}, "
				f"log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
			)
			raise RuntimeError(f"Sheets query failed: {response.code} {response.msg}")
		try:
			self._logger.info(lark.JSON.marshal(response.data, indent=4))
		except Exception:
			pass
		return response

	# ---------- Drive v1：获取单个文件信息（含创建/修改时间） ----------
	def get_drive_file(self, file_token: str) -> Dict[str, Any]:
		try:
			from lark_oapi.api.drive.v1 import GetFileRequest, GetFileResponse
		except ModuleNotFoundError as e:
			raise NotImplementedError(
				"当前 lark-oapi 版本未提供 drive.v1 file.get API。请升级到 >=1.4.15。"
			) from e

		request = GetFileRequest.builder().file_token(file_token).build()
		response: GetFileResponse = self.client.drive.v1.file.get(request)
		if not response.success():
			self._logger.error(
				f"client.drive.v1.file.get failed, code: {response.code}, msg: {response.msg}, "
				f"log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}"
			)
			raise RuntimeError(f"Drive get failed: {response.code} {response.msg}")
		return response.data if response.data is not None else {}

	# ---------- Sheets v2：读取指定范围的值（使用 lark 原生 BaseRequest 调用） ----------
	def read_range_values(
		self,
		spreadsheet_token: str,
		range_a1: str,
		value_render_option: str = "ToString",
		date_time_render_option: str = "FormattedString",
	) -> List[List[Any]]:
		# URL 中的 range 需要进行 path 安全编码，但保留 '!' 和 ':'
		encoded_range = quote(range_a1, safe="!:")
		uri = f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{encoded_range}"

		self._logger.debug(f"准备读取表格范围数据: spreadsheet_token={spreadsheet_token}, range={range_a1}, encoded_range={encoded_range}")

		request = (
			lark.BaseRequest.builder()
			.http_method(lark.HttpMethod.GET)
			.uri(uri)
			.token_types({lark.AccessTokenType.TENANT})
			.queries([
				("valueRenderOption", value_render_option),
				("dateTimeRenderOption", date_time_render_option),
			])
			.build()
		)

		response: lark.BaseResponse = self.client.request(request)
		
		self._logger.debug(f"飞书 API 响应: code={response.code}, success={response.success()}, log_id={response.get_log_id()}")
		
		if not response.success():
			self._logger.error(
				f"飞书 API 错误: {response.code} - valueRange get failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
			)
			raise RuntimeError(
				f"valueRange get failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
			)

		try:
			body = json.loads(response.raw.content.decode("utf-8"))
			self._logger.debug(f"解析响应体成功，数据结构: {json.dumps(body, indent=2, ensure_ascii=False)}")
		except Exception as ex:
			self._logger.error(f"解析响应体失败: {ex}, 原始内容: {response.raw.content}")
			raise RuntimeError(f"invalid json body: {ex}")

		values = (
			(body or {}).get("data", {}).get("valueRange", {}).get("values", [])
			or []
		)
		
		self._logger.debug(f"成功获取表格数据，行数: {len(values)}")
		return values


