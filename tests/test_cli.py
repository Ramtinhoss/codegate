"""Tests for the server module."""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from httpx import AsyncClient

from codegate import __version__
from codegate.pipeline.secrets.manager import SecretsManager
from codegate.providers.registry import ProviderRegistry
from codegate.server import init_app
from src.codegate.cli import UvicornServer
from src.codegate.cli import cli
from src.codegate.codegate_logging import LogLevel, LogFormat
from uvicorn.config import Config as UvicornConfig
from click.testing import CliRunner


@pytest.fixture
def mock_secrets_manager():
    """Create a mock secrets manager."""
    return MagicMock(spec=SecretsManager)


@pytest.fixture
def mock_provider_registry():
    """Create a mock provider registry."""
    return MagicMock(spec=ProviderRegistry)


@pytest.fixture
def test_client() -> TestClient:
    """Create a test client for the FastAPI application."""
    app = init_app()
    return TestClient(app)


def test_app_initialization() -> None:
    """Test that the FastAPI application initializes correctly."""
    app = init_app()
    assert app is not None
    assert app.title == "CodeGate"
    assert app.version == __version__


def test_cors_middleware() -> None:
    """Test that CORS middleware is properly configured."""
    app = init_app()
    cors_middleware = None
    for middleware in app.user_middleware:
        if isinstance(middleware.cls, type) and issubclass(middleware.cls, CORSMiddleware):
            cors_middleware = middleware
            break
    assert cors_middleware is not None
    assert cors_middleware.kwargs.get("allow_origins") == ["*"]
    assert cors_middleware.kwargs.get("allow_credentials") is True
    assert cors_middleware.kwargs.get("allow_methods") == ["*"]
    assert cors_middleware.kwargs.get("allow_headers") == ["*"]


def test_health_check(test_client: TestClient) -> None:
    """Test the health check endpoint."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@patch("codegate.server.ProviderRegistry")
@patch("codegate.server.SecretsManager")
def test_provider_registration(mock_secrets_mgr, mock_registry) -> None:
    """Test that all providers are registered correctly."""
    init_app()

    # Verify SecretsManager was initialized
    mock_secrets_mgr.assert_called_once()

    # Verify ProviderRegistry was initialized with the app
    mock_registry.assert_called_once()

    # Verify all providers were registered
    registry_instance = mock_registry.return_value
    assert (
        registry_instance.add_provider.call_count == 5
    )  # openai, anthropic, llamacpp, vllm, ollama

    # Verify specific providers were registered
    provider_names = [call.args[0] for call in registry_instance.add_provider.call_args_list]
    assert "openai" in provider_names
    assert "anthropic" in provider_names
    assert "llamacpp" in provider_names
    assert "vllm" in provider_names
    assert "ollama" in provider_names


@patch("codegate.server.CodegateSignatures")
def test_signatures_initialization(mock_signatures) -> None:
    """Test that signatures are initialized correctly."""
    init_app()
    mock_signatures.initialize.assert_called_once_with("signatures.yaml")


def test_pipeline_initialization() -> None:
    """Test that pipelines are initialized correctly."""
    app = init_app()

    # Access the provider registry to check pipeline configuration
    registry = next((route for route in app.routes if hasattr(route, "registry")), None)

    if registry:
        for provider in registry.registry.values():
            # Verify each provider has the required pipelines
            assert hasattr(provider, "pipeline_processor")
            assert hasattr(provider, "fim_pipeline_processor")
            assert hasattr(provider, "output_pipeline_processor")


def test_dashboard_routes() -> None:
    """Test that dashboard routes are included."""
    app = init_app()
    routes = [route.path for route in app.routes]

    # Verify dashboard endpoints are included
    dashboard_routes = [route for route in routes if route.startswith("/dashboard")]
    assert len(dashboard_routes) > 0


def test_system_routes() -> None:
    """Test that system routes are included."""
    app = init_app()
    routes = [route.path for route in app.routes]

    # Verify system endpoints are included
    assert "/health" in routes


@pytest.mark.asyncio
async def test_async_health_check() -> None:
    """Test the health check endpoint with async client."""
    app = init_app()
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


def test_error_handling(test_client: TestClient) -> None:
    """Test error handling for non-existent endpoints."""
    response = test_client.get("/nonexistent")
    assert response.status_code == 404

    # Test method not allowed
    response = test_client.post("/health")  # Health endpoint only allows GET
    assert response.status_code == 405


@pytest.fixture
def mock_app():
    # Create a simple mock for the ASGI application
    return MagicMock()


@pytest.fixture
def uvicorn_config(mock_app):
    # Assuming mock_app is defined to simulate ASGI application
    return UvicornConfig(app=mock_app, host='localhost', port=8000, log_level='info')


@pytest.fixture
def server_instance(uvicorn_config):
    with patch('src.codegate.cli.Server', autospec=True) as mock_server_class:
        mock_server_instance = mock_server_class.return_value
        mock_server_instance.serve = AsyncMock()
        yield UvicornServer(uvicorn_config, mock_server_instance)


@pytest.mark.asyncio
async def test_server_starts_and_runs(server_instance):
    await server_instance.serve()
    server_instance.server.serve.assert_awaited_once()


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def mock_logging(mocker):
    return mocker.patch('your_cli_module.structlog.get_logger')


@pytest.fixture
def mock_setup_logging(mocker):
    return mocker.patch('your_cli_module.setup_logging')


def test_serve_default_options(cli_runner):
    """Test serve command with default options."""
    # Use patches for run_servers and logging setup
    with patch("src.codegate.cli.run_servers") as mock_run, \
         patch("src.codegate.cli.structlog.get_logger") as mock_logging, \
         patch("src.codegate.cli.setup_logging") as mock_setup_logging:

        logger_instance = MagicMock()
        mock_logging.return_value = logger_instance

        # Invoke the CLI command
        result = cli_runner.invoke(cli, ["serve"])

        # Basic checks to ensure the command executed successfully
        assert result.exit_code == 0

        # Check if the logging setup was called with expected defaults
        mock_setup_logging.assert_called_once_with(LogLevel.INFO, LogFormat.JSON)

        # Check if logging was done correctly
        mock_logging.assert_called_with("codegate")

        # Validate run_servers was called once
        mock_run.assert_called_once()


def test_serve_custom_options(cli_runner):
    """Test serve command with custom options."""
    with patch("src.codegate.cli.run_servers") as mock_run, \
         patch("src.codegate.cli.structlog.get_logger") as mock_logging, \
         patch("src.codegate.cli.setup_logging") as mock_setup_logging:

        logger_instance = MagicMock()
        mock_logging.return_value = logger_instance

        # Invoke the CLI command with custom options
        result = cli_runner.invoke(
            cli,
            [
                "serve",
                "--port", "8989",
                "--host", "localhost",
                "--log-level", "DEBUG",
                "--log-format", "TEXT",
                "--certs-dir", "./custom-certs",
                "--ca-cert", "custom-ca.crt",
                "--ca-key", "custom-ca.key",
                "--server-cert", "custom-server.crt",
                "--server-key", "custom-server.key",
            ],
        )

        # Check the command executed successfully
        assert result.exit_code == 0

        # Assert logging setup was called with the provided log level and format
        mock_setup_logging.assert_called_once_with(LogLevel.DEBUG, LogFormat.TEXT)

        # Assert logger got called with the expected module name
        mock_logging.assert_called_with("codegate")

        # Validate run_servers was called once
        mock_run.assert_called_once()
        # Retrieve the actual Config object passed to run_servers
        config_arg = mock_run.call_args[0][0]  # Assuming Config is the first positional arg

        # Define expected values that should be present in the Config object
        expected_values = {
            "port": 8989,
            "host": "localhost",
            "log_level": LogLevel.DEBUG,
            "log_format": LogFormat.TEXT,
            "certs_dir": "./custom-certs",
            "ca_cert": "custom-ca.crt",
            "ca_key": "custom-ca.key",
            "server_cert": "custom-server.crt",
            "server_key": "custom-server.key",
        }

        # Check if Config object attributes match the expected values
        for key, expected_value in expected_values.items():
            assert getattr(config_arg, key) == expected_value, f"{key} does not match expected value"


def test_serve_invalid_port(cli_runner):
    """Test serve command with invalid port."""
    result = cli_runner.invoke(cli, ["serve", "--port", "999999"])
    assert result.exit_code == 2  # Typically 2 is used for CLI errors in Click
    assert "Port must be between 1 and 65535" in result.output


def test_serve_invalid_log_level(cli_runner):
    """Test serve command with invalid log level."""
    result = cli_runner.invoke(cli, ["serve", "--log-level", "INVALID"])
    assert result.exit_code == 2
    assert "Invalid value for '--log-level'" in result.output


@pytest.fixture
def temp_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
    log_level: DEBUG
    log_format: JSON
    port: 8989
    host: localhost
    certs_dir: ./test-certs
    """)
    return config_path


def test_serve_with_config_file(cli_runner, temp_config_file):
    """Test serve command with config file."""
    with patch("src.codegate.cli.run_servers") as mock_run, \
         patch("src.codegate.cli.structlog.get_logger") as mock_logging, \
         patch("src.codegate.cli.setup_logging") as mock_setup_logging:

        logger_instance = MagicMock()
        mock_logging.return_value = logger_instance

        # Invoke the CLI command with the configuration file
        result = cli_runner.invoke(cli, ["serve", "--config", str(temp_config_file)])

        # Assertions to ensure the CLI ran successfully
        assert result.exit_code == 0
        mock_setup_logging.assert_called_once_with(LogLevel.DEBUG, LogFormat.JSON)
        mock_logging.assert_called_with("codegate")

        # Validate that run_servers was called with the expected configuration
        mock_run.assert_called_once()
        config_arg = mock_run.call_args[0][0]  # Assuming Config object is the first positional argument

        # Define expected values based on the temp_config_file content
        expected_values = {
            "port": 8989,
            "host": "localhost",
            "log_level": LogLevel.DEBUG,
            "log_format": LogFormat.JSON,
            "certs_dir": "./test-certs",
        }

        # Check if passed arguments match the expected values
        for key, expected_value in expected_values.items():
            assert getattr(config_arg, key) == expected_value, f"{key} does not match expected value"

