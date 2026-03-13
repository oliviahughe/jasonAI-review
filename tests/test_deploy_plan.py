import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stub_openai_module():
    module = types.ModuleType("openai")

    class _DummyOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.OpenAI = _DummyOpenAI
    return module


def _stub_chromadb_module():
    module = types.ModuleType("chromadb")

    class _DummyClient:
        def __init__(self, path):
            self.path = path

    module.PersistentClient = _DummyClient
    return module


def _stub_fastmcp_module():
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class _DummyFastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self, **kwargs):
            return kwargs

        def sse_app(self, mount_path=None):
            class _DummyApp:
                def __init__(self):
                    self.middlewares = []

                def add_middleware(self, middleware_cls):
                    self.middlewares.append(middleware_cls)

            return _DummyApp()

        def streamable_http_app(self):
            class _DummyApp:
                def __init__(self):
                    self.middlewares = []

                def add_middleware(self, middleware_cls):
                    self.middlewares.append(middleware_cls)

            return _DummyApp()

    fastmcp_module.FastMCP = _DummyFastMCP
    return fastmcp_module


def _stub_requests_module():
    module = types.ModuleType("requests")
    module.RequestException = Exception
    module.get = lambda *args, **kwargs: None
    return module


def _stub_bs4_module():
    module = types.ModuleType("bs4")

    class _DummySoup:
        def __init__(self, *args, **kwargs):
            pass

    module.BeautifulSoup = _DummySoup
    return module


def _stub_markdownify_module():
    module = types.ModuleType("markdownify")
    module.markdownify = lambda text, **kwargs: text
    return module


def _stub_starlette_modules():
    base_module = types.ModuleType("starlette.middleware.base")
    responses_module = types.ModuleType("starlette.responses")
    starlette_module = types.ModuleType("starlette")
    middleware_module = types.ModuleType("starlette.middleware")

    class _DummyBaseHTTPMiddleware:
        def __init__(self, app=None):
            self.app = app

    class _DummyPlainTextResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code

    base_module.BaseHTTPMiddleware = _DummyBaseHTTPMiddleware
    responses_module.PlainTextResponse = _DummyPlainTextResponse

    return {
        "starlette": starlette_module,
        "starlette.middleware": middleware_module,
        "starlette.middleware.base": base_module,
        "starlette.responses": responses_module,
    }


def _stub_yaml_module():
    module = types.ModuleType("yaml")

    def safe_load(text):
        if hasattr(text, "read"):
            text = text.read()
        data = {}
        current = None
        for raw_line in str(text).splitlines():
            line = raw_line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            if not raw_line.startswith("  "):
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip('"')
                if value:
                    data[key] = value
                    current = None
                else:
                    data[key] = {}
                    current = data[key]
            else:
                key, _, value = line.strip().partition(":")
                if current is not None:
                    current[key.strip()] = value.strip().strip('"')
        return data

    def dump(data, stream=None, **kwargs):
        rendered = str(data)
        if stream is not None:
            stream.write(rendered)
            return None
        return rendered

    module.safe_load = safe_load
    module.dump = dump
    return module


def _load_module(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    stubs = {
        "openai": _stub_openai_module(),
        "chromadb": _stub_chromadb_module(),
        "mcp.server.fastmcp": _stub_fastmcp_module(),
        "mcp": types.ModuleType("mcp"),
        "mcp.server": types.ModuleType("mcp.server"),
        "yaml": _stub_yaml_module(),
        "crawl": types.SimpleNamespace(crawl_article=lambda *args, **kwargs: {}),
        "requests": _stub_requests_module(),
        "bs4": _stub_bs4_module(),
        "markdownify": _stub_markdownify_module(),
    }
    stubs.update(_stub_starlette_modules())

    previous = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


class DeployPlanTests(unittest.TestCase):
    def test_load_settings_supports_env_override(self):
        ingest = _load_module("deploy_ingest_env", "scripts/ingest.py")
        tmpdir = REPO_ROOT / "tests" / "_tmp_env_override"
        config_dir = tmpdir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_path = config_dir / "settings.yaml"
        settings_path.write_text(
            "\n".join(
                [
                    "openai:",
                    '  api_key: "placeholder"',
                    '  base_url: "https://example.invalid/v1"',
                    '  embedding_model: "text-embedding-3-small"',
                    "paths:",
                    '  raw_dir: "raw"',
                    '  chroma_dir: "chroma_db"',
                ]
            ),
            encoding="utf-8",
        )

        try:
            with patch.object(ingest, "__file__", str(tmpdir / "scripts" / "ingest.py")):
                with patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "env-key",
                        "OPENAI_BASE_URL": "https://override.invalid/v1",
                    },
                    clear=False,
                ):
                    settings = ingest.load_settings()
        finally:
            if settings_path.exists():
                settings_path.unlink()
            if config_dir.exists():
                config_dir.rmdir()
            if tmpdir.exists():
                tmpdir.rmdir()

        self.assertEqual(settings["openai"]["api_key"], "env-key")
        self.assertEqual(settings["openai"]["base_url"], "https://override.invalid/v1")

    def test_get_project_root_uses_data_dir_when_present(self):
        ingest = _load_module("deploy_ingest_data_dir", "scripts/ingest.py")

        with patch.dict(os.environ, {"DATA_DIR": "/srv/jason-data"}, clear=False):
            data_root = ingest.get_data_root()

        self.assertEqual(Path("/srv/jason-data"), data_root)

    def test_main_uses_streamable_http_transport_when_requested(self):
        mcp_server = _load_module("deploy_mcp_server", "scripts/mcp_server.py")

        with patch.dict(os.environ, {"MCP_TRANSPORT": "streamable_http", "PORT": "9090"}, clear=False):
            with patch.object(mcp_server.mcp, "run") as run_mock:
                mcp_server.main()

        run_mock.assert_called_once_with(transport="streamable-http")

    def test_main_uses_uvicorn_when_auth_token_is_configured_for_streamable_http(self):
        mcp_server = _load_module("deploy_mcp_server_uvicorn", "scripts/mcp_server.py")
        uvicorn_calls = []
        uvicorn_stub = types.SimpleNamespace(
            run=lambda app, host, port: uvicorn_calls.append(
                {"app": app, "host": host, "port": port}
            )
        )
        runtime_stubs = {"uvicorn": uvicorn_stub}
        runtime_stubs.update(_stub_starlette_modules())

        with patch.dict(
            os.environ,
            {"MCP_TRANSPORT": "streamable_http", "PORT": "9091", "AUTH_TOKEN": "secret"},
            clear=False,
        ):
            with patch.dict(sys.modules, runtime_stubs):
                mcp_server.main()

        self.assertEqual(1, len(uvicorn_calls))
        self.assertEqual("0.0.0.0", uvicorn_calls[0]["host"])
        self.assertEqual(9091, uvicorn_calls[0]["port"])

    def test_main_rejects_unknown_transport(self):
        mcp_server = _load_module("deploy_mcp_server_invalid_transport", "scripts/mcp_server.py")

        with patch.dict(os.environ, {"MCP_TRANSPORT": "bogus-transport"}, clear=False):
            with self.assertRaises(ValueError):
                mcp_server.main()

    def test_resolve_path_uses_data_dir_for_runtime_data(self):
        mcp_server = _load_module("deploy_mcp_server_paths", "scripts/mcp_server.py")

        with patch.dict(os.environ, {"DATA_DIR": "/data"}, clear=False):
            resolved = mcp_server._resolve_path("profile/demo.yaml")

        self.assertEqual(Path("/data/profile/demo.yaml"), resolved)

    def test_ingest_article_resolves_relative_paths_against_data_dir(self):
        mcp_server = _load_module("deploy_mcp_server_ingest_path", "scripts/mcp_server.py")

        with patch.dict(os.environ, {"DATA_DIR": "/data"}, clear=False):
            with patch.object(mcp_server, "_get_settings", return_value={}):
                with patch.object(mcp_server, "_ingest_article") as ingest_mock:
                    ingest_mock.return_value = {"status": "ok", "message": "ingested"}
                    mcp_server.ingest_article("raw/demo.md")

        ingest_mock.assert_called_once_with(str(Path("/data/raw/demo.md")), {})

    def test_auth_check_accepts_matching_bearer_token(self):
        mcp_server = _load_module("deploy_mcp_server_auth", "scripts/mcp_server.py")

        with patch.dict(os.environ, {"AUTH_TOKEN": "secret-token"}, clear=False):
            self.assertTrue(
                mcp_server._is_authorized({"authorization": "Bearer secret-token"})
            )
            self.assertFalse(mcp_server._is_authorized({"authorization": "Bearer wrong"}))

    def test_crawl_uses_data_dir_for_raw_storage(self):
        crawl = _load_module("deploy_crawl_data_dir", "scripts/crawl.py")

        with patch.dict(os.environ, {"DATA_DIR": "/data"}, clear=False):
            data_root = crawl.get_data_root()

        self.assertEqual(Path("/data"), data_root)

    def test_crawl_article_rejects_non_2xx_http_responses(self):
        crawl = _load_module("deploy_crawl_http_errors", "scripts/crawl.py")

        class _DummyTag:
            def __init__(self, text):
                self._text = text

            def get_text(self, strip=False):
                return self._text.strip() if strip else self._text

            def find_all(self, names):
                return []

        class _DummyResponse:
            text = "<html><body>blocked</body></html>"
            encoding = "utf-8"

            def raise_for_status(self):
                raise crawl.requests.RequestException("403 Client Error")

        class _DummySoup:
            def __init__(self, text, parser):
                self.text = text

            def find(self, name=None, class_=None, id=None):
                if name == "h1":
                    return _DummyTag("blocked")
                if name == "article":
                    return _DummyTag("blocked page")
                if name == "body":
                    return _DummyTag("blocked page")
                return None

            def select_one(self, selector):
                return _DummyTag("blocked page")

        settings = {"crawl": {"user_agent": "ua", "timeout": 5}}

        with patch.object(crawl.requests, "get", return_value=_DummyResponse()):
            with patch.object(crawl, "BeautifulSoup", _DummySoup):
                with patch.object(crawl, "md", lambda text, **kwargs: "blocked page"):
                    with patch.object(crawl, "save_article") as save_mock:
                        result = crawl.crawl_article("https://example.com/blocked", "知识星球", settings)

        save_mock.assert_not_called()
        self.assertEqual("error", result["status"])
        self.assertIn("网络请求失败", result["message"])

    def test_migrate_data_copies_seed_data_when_volume_empty(self):
        migrate = _load_module("deploy_migrate_data", "scripts/migrate_data.py")

        source_root = REPO_ROOT / "tests" / "_tmp_source_seed"
        data_root = REPO_ROOT / "tests" / "_tmp_data_seed"
        profile_dir = source_root / "profile"
        raw_dir = source_root / "raw"
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "demo.txt").write_text("profile", encoding="utf-8")
            (raw_dir / "article.md").write_text("article", encoding="utf-8")

            copied = migrate.sync_seed_data(source_root=source_root, data_root=data_root)
        finally:
            # cleanup after assertions below
            pass

        self.assertTrue(copied)
        self.assertTrue((data_root / "profile" / "demo.txt").exists())
        self.assertTrue((data_root / "raw" / "article.md").exists())

        file_paths = [
            data_root / "profile" / "demo.txt",
            data_root / "raw" / "article.md",
            profile_dir / "demo.txt",
            raw_dir / "article.md",
        ]
        dir_paths = [
            data_root / "profile",
            data_root / "raw",
            data_root,
            profile_dir,
            raw_dir,
            source_root,
        ]
        for path in file_paths:
            if path.exists():
                path.unlink()
        for path in dir_paths:
            if path.exists():
                path.rmdir()


if __name__ == "__main__":
    unittest.main()
