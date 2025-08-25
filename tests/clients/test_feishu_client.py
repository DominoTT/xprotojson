import sys
import json
import types

import pytest


def _install_fake_drive_modules():
    mod = types.ModuleType("lark_oapi.api.drive.v1")

    class ListFileRequest:
        @classmethod
        def builder(cls):
            class _B:
                def __init__(self):
                    self._page_size = None
                    self._folder_token = None
                    self._order_by = None
                    self._direction = None
                    self._user_id_type = None

                def page_size(self, v):
                    self._page_size = v
                    return self

                def folder_token(self, v):
                    self._folder_token = v
                    return self

                def order_by(self, v):
                    self._order_by = v
                    return self

                def direction(self, v):
                    self._direction = v
                    return self

                def user_id_type(self, v):
                    self._user_id_type = v
                    return self

                def page_token(self, v):
                    self._page_token = v
                    return self

                def build(self):
                    return self

            return _B()

    class ListFileResponse:
        pass

    mod.ListFileRequest = ListFileRequest
    mod.ListFileResponse = ListFileResponse
    sys.modules["lark_oapi.api.drive.v1"] = mod


class _FakeJSON:
    @staticmethod
    def marshal(obj, indent=4):
        return json.dumps(obj, indent=indent, ensure_ascii=False)


class _FakeBaseRequest:
    @classmethod
    def builder(cls):
        class _B:
            def http_method(self, _):
                return self

            def uri(self, _):
                return self

            def token_types(self, _):
                return self

            def queries(self, _):
                return self

            def build(self):
                return object()

        return _B()


class _FakeResponse:
    def __init__(self, data=None, ok=True, body=None, code=0, msg="ok"):
        self.data = data
        self._ok = ok
        self.code = code
        self.msg = msg
        # mimic lark BaseResponse.raw.content
        raw = types.SimpleNamespace()
        raw.content = json.dumps(body or {}).encode("utf-8")
        self.raw = raw

    def success(self):
        return self._ok

    def get_log_id(self):
        return "log-id"


class _FakeClientBuilder:
    def __init__(self):
        self._app_id = None
        self._app_secret = None
        self._log_level = None

    def app_id(self, v):
        self._app_id = v
        return self

    def app_secret(self, v):
        self._app_secret = v
        return self

    def log_level(self, v):
        self._log_level = v
        return self

    def build(self):
        # sheets
        spreadsheet_sheet = types.SimpleNamespace()
        sheets_v3 = types.SimpleNamespace(spreadsheet_sheet=spreadsheet_sheet)
        sheets = types.SimpleNamespace(v3=sheets_v3)

        # drive
        drive_v1 = types.SimpleNamespace(file=types.SimpleNamespace())
        drive = types.SimpleNamespace(v1=drive_v1)

        client = types.SimpleNamespace()
        client.sheets = sheets
        client.drive = drive
        client._query_response = _FakeResponse(data={})
        client._drive_response = _FakeResponse(data={})
        client._base_response = _FakeResponse(body={})

        def query(request):
            return client._query_response

        def file_list(request):
            return client._drive_response

        def request_fn(_):
            return client._base_response

        spreadsheet_sheet.query = query
        drive_v1.file.list = file_list
        client.request = request_fn
        return client


@pytest.fixture(autouse=True)
def _patch_lark(monkeypatch):
    # Patch lark module pieces used by FeishuClient
    import app.clients.feishu as mod
    monkeypatch.setattr(mod.lark, "Client", types.SimpleNamespace(builder=_FakeClientBuilder))
    monkeypatch.setattr(mod, "QuerySpreadsheetSheetRequest", _make_qreq())
    # JSON marshal used in log path
    monkeypatch.setattr(mod.lark, "JSON", _FakeJSON)
    # BaseRequest and enums used in read_range_values
    monkeypatch.setattr(mod.lark, "BaseRequest", _FakeBaseRequest)
    monkeypatch.setattr(mod.lark, "HttpMethod", types.SimpleNamespace(GET="GET"))
    monkeypatch.setattr(mod.lark, "AccessTokenType", types.SimpleNamespace(TENANT="TENANT"))
    _install_fake_drive_modules()
    yield


def _make_qreq():
    class _Q:
        @classmethod
        def builder(cls):
            class _B:
                def __init__(self):
                    self._token = None

                def spreadsheet_token(self, v):
                    self._token = v
                    return self

                def build(self):
                    return self

            return _B()

    return _Q


def test_init_and_list_sheets(monkeypatch):
    from app.clients import FeishuClient

    client = FeishuClient(app_id="id", app_secret="secret")
    # configure query response
    client.client._query_response = _FakeResponse(data={"ok": 1})
    resp = client.list_sheets("sht_token")
    assert resp.success()
    assert resp.data == {"ok": 1}


def test_read_range_values():
    from app.clients import FeishuClient

    fc = FeishuClient(app_id="id", app_secret="secret")
    body = {"data": {"valueRange": {"values": [["a", "b"], ["c", "d"]]}}}
    fc.client._base_response = _FakeResponse(body=body)
    values = fc.read_range_values("sht", "Sheet1!A1:B2")
    assert values == [["a", "b"], ["c", "d"]]


def test_list_drive_files():
    from app.clients import FeishuClient

    fc = FeishuClient(app_id="id", app_secret="secret")
    fc.client._drive_response = _FakeResponse(data={"files": []})
    data = fc.list_drive_files(folder_token="fld_token")
    assert "files" in data
    assert data["files"] == []


