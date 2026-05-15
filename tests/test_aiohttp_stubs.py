"""Shared aiohttp stubs for unit tests that import Home Assistant integrations."""

from __future__ import annotations

from typing import Any, Callable
import sys
import types


def ensure_aiohttp_stubs() -> None:
    """Install a tiny aiohttp stub module when aiohttp is unavailable."""

    if "aiohttp" in sys.modules:
        return
    try:
        import aiohttp  # type: ignore[import-not-found]

        sys.modules["aiohttp"] = aiohttp
        return
    except Exception:
        pass

    aiohttp_module = types.ModuleType("aiohttp")

    class _ClientTimeout:
        def __init__(self, *, total: float | None = None):
            self.total = total

    class _WSMsgType:
        CLOSE = "CLOSE"
        CLOSED = "CLOSED"
        CLOSING = "CLOSING"
        ERROR = "ERROR"
        TEXT = "TEXT"
        BINARY = "BINARY"

    class _ClientSession:
        def __init__(self, *args, **kwargs):
            self._closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            await self.close()

        async def close(self):
            self._closed = True

    for name in [
        "ClientResponse",
        "RequestInfo",
        "ClientResponseError",
        "ContentTypeError",
        "ClientError",
        "ClientPayloadError",
        "ClientConnectionError",
        "ClientConnectorError",
        "ServerDisconnectedError",
        "ServerTimeoutError",
        "InvalidURL",
        "ClientConnectionResetError",
        "WSServerHandshakeError",
    ]:
        setattr(aiohttp_module, name, type(name, (Exception,), {}))

    class _FormData:
        def __init__(self, *args, **kwargs):
            self._fields = list(args)
            self._kwargs = kwargs

    class _ClientWebSocketResponse:
        async def send_json(self, *_args, **_kwargs) -> None:
            return None

    class _WSMessage:
        TYPE_TEXT = "text"

        def __init__(self, *args, **kwargs):
            self.data = kwargs.get("data", "")
            self.type = self.TYPE_TEXT

    class _ClientResponse:
        status = 200

        def __init__(self, *args, **kwargs):
            self.reason = ""
            self.content_type = ""
            self.headers = {}

        async def read(self):
            return b""

        async def text(self):
            return ""

    class _WebSocketResponse:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def prepare(self, request):
            return self

        async def send_str(self, *_args, **_kwargs):
            return None

    class _Request:
        pass

    class _Response:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class _AppKey:
        def __init__(self, *args, **kwargs) -> None:
            self.key = args[0] if args else None

        def __repr__(self) -> str:
            return f"AppKey({self.key!r})"

        @classmethod
        def __class_getitem__(cls, _item):
            return cls

    class _AbstractStreamWriter:
        async def write(self, *_args, **_kwargs):
            return None

    class _RawRequestMessage:
        pass

    class _StreamReader:
        pass

    class _RequestHandler:
        pass

    class _SockSite:
        def __init__(self, runner, sock, ssl_context=None):
            self._runner = runner
            self._sock = sock
            self._ssl_context = ssl_context

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    web_module = types.ModuleType("aiohttp.web")

    class _AbstractResource:
        canonical = "/"

    class _Resource(_AbstractResource):
        pass

    class _AbstractRoute:
        def __init__(self, *args, **kwargs) -> None:
            self.resource = _Resource()

    class _ResourceRoute(_AbstractRoute):
        pass

    class _StaticResource(_Resource):
        pass

    web_module.Request = _Request
    web_module.WebSocketResponse = _WebSocketResponse
    web_module.Response = _Response
    web_module.FileResponse = _Response
    web_module.StreamResponse = _Response
    web_module.json_response = _Response
    web_module.AppKey = _AppKey
    web_module.WSMessage = _WSMessage
    web_module.ClientWebSocketResponse = _ClientWebSocketResponse
    web_module.SockSite = _SockSite
    web_module.StaticResource = _StaticResource

    class _BaseRunner:
        def __init__(self, *args, **kwargs) -> None:
            self._closed = False
            self._server = None

        async def cleanup(self) -> None:
            self._closed = True

    class _BaseSite:
        def __init__(self, runner, ssl_context=None, backlog=128, **kwargs) -> None:
            self._runner = runner
            self._ssl_context = ssl_context
            self._backlog = backlog

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    web_module.BaseRunner = _BaseRunner
    web_module.BaseSite = _BaseSite

    class _AppRunner:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __repr__(self) -> str:
            return "AppRunner()"

    def _middleware(handler=None):
        if handler is None:
            def _decorator(inner):
                return inner

            return _decorator

        return handler

    web_module.AppRunner = _AppRunner
    web_module.Application = object
    web_module.HTTPBadRequest = None
    web_module.HTTPInternalServerError = None
    web_module.HTTPForbidden = None
    web_module.middleware = _middleware
    web_module.View = object

    class _Application:
        def __init__(self, *args, **kwargs) -> None:
            self.middlewares = []

        def add_routes(self, *args, **kwargs) -> None:
            return None

        def add_subapp(self, *args, **kwargs) -> None:
            return None

    class _BadRequest(Exception):
        pass

    web_module.Application = _Application
    web_module.BadRequestException = _BadRequest
    web_module.HTTPException = Exception

    web_module.HTTPBadRequest = None
    web_module.HTTPInternalServerError = None
    web_module.HTTPForbidden = None
    web_module.HTTPNotFound = None
    web_module.HTTPMovedPermanently = None
    web_module.HTTPMethodNotAllowed = None
    web_module.HTTPRedirection = None
    web_module.HTTPBadGateway = None
    web_module.HTTPGatewayTimeout = None

    def _web_getattr(name):
        if name in web_exceptions_module.__dict__:
            return getattr(web_exceptions_module, name)
        if name == "Application":
            return _Application
        if name == "StreamResponse":
            return _Response
        if name == "Request":
            return _Request
        if name == "Response":
            return _Response
        if name == "WebSocketResponse":
            return _WebSocketResponse
        if name == "FileResponse":
            return _Response
        if name == "json_response":
            return _Response
        if name == "middleware":
            return _middleware
        raise AttributeError(name)

    web_module.__getattr__ = _web_getattr

    typedefs_module = types.ModuleType("aiohttp.typedefs")
    typedefs_module.LooseHeaders = dict[str, str]
    typedefs_module.JSONDecoder = object
    typedefs_module.StrOrURL = str
    typedefs_module.Query = dict[str, str] | None

    http_websocket_module = types.ModuleType("aiohttp.http_websocket")

    class _WebSocketWriter:
        def __init__(self, *args, **kwargs):
            pass

    http_websocket_module.WebSocketWriter = _WebSocketWriter

    web_urldispatcher_module = types.ModuleType("aiohttp.web_urldispatcher")
    web_urldispatcher_module.AbstractResource = _AbstractResource
    web_urldispatcher_module.AbstractRoute = _AbstractRoute
    web_urldispatcher_module.Resource = _Resource
    web_urldispatcher_module.ResourceRoute = _ResourceRoute
    web_urldispatcher_module.StaticResource = _StaticResource

    hdrs_module = types.ModuleType("aiohttp.hdrs")
    hdrs_module.HOST = "Host"
    hdrs_module.AUTHORIZATION = "Authorization"
    hdrs_module.ACCEPT = "Accept"
    hdrs_module.CONTENT_TYPE = "Content-Type"
    hdrs_module.CONTENT_DISPOSITION = "Content-Disposition"
    hdrs_module.USER_AGENT = "User-Agent"
    hdrs_module.ORIGIN = "Origin"
    hdrs_module.CACHE_CONTROL = "Cache-Control"
    hdrs_module.EXPIRES = "Expires"
    hdrs_module.LAST_MODIFIED = "Last-Modified"
    hdrs_module.PRAGMA = "Pragma"
    hdrs_module.ACCESS_CONTROL_ALLOW_ORIGIN = "Access-Control-Allow-Origin"
    hdrs_module.ACCESS_CONTROL_ALLOW_CREDENTIALS = "Access-Control-Allow-Credentials"
    hdrs_module.ACCESS_CONTROL_EXPOSE_HEADERS = "Access-Control-Expose-Headers"
    hdrs_module.ACCESS_CONTROL_ALLOW_HEADERS = "Access-Control-Allow-Headers"
    hdrs_module.ACCESS_CONTROL_ALLOW_METHODS = "Access-Control-Allow-Methods"
    hdrs_module.X_FORWARDED_FOR = "X-Forwarded-For"
    hdrs_module.X_FORWARDED_HOST = "X-Forwarded-Host"
    hdrs_module.X_FORWARDED_PROTO = "X-Forwarded-Proto"
    hdrs_module.istr = "istr"
    hdrs_module.CONTENT_LANGUAGE = "Content-Language"
    hdrs_module.METH_GET = "GET"
    hdrs_module.METH_POST = "POST"
    hdrs_module.METH_PUT = "PUT"
    hdrs_module.METH_DELETE = "DELETE"
    hdrs_module.METH_PATCH = "PATCH"
    hdrs_module.METH_HEAD = "HEAD"
    hdrs_module.METH_OPTIONS = "OPTIONS"

    abc_module = types.ModuleType("aiohttp.abc")
    abc_module.AbstractStreamWriter = _AbstractStreamWriter
    http_parser_module = types.ModuleType("aiohttp.http_parser")
    http_parser_module.RawRequestMessage = _RawRequestMessage
    streams_module = types.ModuleType("aiohttp.streams")
    streams_module.StreamReader = _StreamReader
    web_protocol_module = types.ModuleType("aiohttp.web_protocol")
    web_protocol_module.RequestHandler = _RequestHandler
    web_fileresponse_module = types.ModuleType("aiohttp.web_fileresponse")

    class _ContentTypes:
        @staticmethod
        def guess_file_type(_path):
            return (None, None, None)

    web_fileresponse_module.CONTENT_TYPES = _ContentTypes()
    web_fileresponse_module.FALLBACK_CONTENT_TYPE = "application/octet-stream"

    web_exceptions_module = types.ModuleType("aiohttp.web_exceptions")
    for _name in [
        "HTTPException",
        "HTTPBadRequest",
        "HTTPInternalServerError",
        "HTTPUnauthorized",
        "HTTPMethodNotAllowed",
        "HTTPForbidden",
        "HTTPNotFound",
        "HTTPMovedPermanently",
        "HTTPRedirection",
        "HTTPBadGateway",
        "HTTPGatewayTimeout",
    ]:
        setattr(web_exceptions_module, _name, type(_name, (Exception,), {}))

    client_exceptions_module = types.ModuleType("aiohttp.client_exceptions")
    for _name in [
        "ClientError",
        "ClientResponseError",
        "ClientPayloadError",
        "WSServerHandshakeError",
    ]:
        setattr(client_exceptions_module, _name, getattr(aiohttp_module, _name))

    aiohttp_module.typedefs = typedefs_module
    aiohttp_module.web_exceptions = web_exceptions_module
    aiohttp_module.web_urldispatcher = web_urldispatcher_module
    aiohttp_module.http_websocket = http_websocket_module
    aiohttp_module.hdrs = hdrs_module
    aiohttp_module.ClientSession = _ClientSession
    aiohttp_module.abc = abc_module
    aiohttp_module.http_parser = http_parser_module
    aiohttp_module.streams = streams_module
    aiohttp_module.web_protocol = web_protocol_module
    aiohttp_module.web_fileresponse = web_fileresponse_module
    aiohttp_module.client_exceptions = client_exceptions_module
    aiohttp_module.FormData = _FormData
    aiohttp_module.StreamReader = _StreamReader
    aiohttp_module.ClientMiddlewareType = Callable[[Callable[[Any], Any]], Callable[[Any], Any]]

    sys.modules["aiohttp.typedefs"] = typedefs_module
    sys.modules["aiohttp.web_exceptions"] = web_exceptions_module
    sys.modules["aiohttp.web_urldispatcher"] = web_urldispatcher_module
    sys.modules["aiohttp.http_websocket"] = http_websocket_module
    sys.modules["aiohttp.hdrs"] = hdrs_module
    sys.modules["aiohttp.abc"] = abc_module
    sys.modules["aiohttp.http_parser"] = http_parser_module
    sys.modules["aiohttp.streams"] = streams_module
    sys.modules["aiohttp.web_protocol"] = web_protocol_module
    sys.modules["aiohttp.web_fileresponse"] = web_fileresponse_module
    sys.modules["aiohttp.client_exceptions"] = client_exceptions_module
    aiohttp_module.web = web_module
    aiohttp_module.ClientTimeout = _ClientTimeout
    aiohttp_module.WSMsgType = _WSMsgType
    aiohttp_module.WSMessage = _WSMessage
    aiohttp_module.ClientWebSocketResponse = _ClientWebSocketResponse
    aiohttp_module.ClientResponse = _ClientResponse
    sys.modules["aiohttp"] = aiohttp_module
    sys.modules["aiohttp.web"] = web_module


_ensure_aiohttp_stub = ensure_aiohttp_stubs
