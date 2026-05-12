import pytest

from shared.clients.factory import (
    DataClientNotConfigured,
    make_market_data_client,
)
from shared.clients.mock_market_data import MockDataClient
from shared.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "DATABASE_PATH": "/tmp/factory_test.db",
        "DATA_CLIENT": "mock",
        "MOCK_SEED": 42,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_factory_returns_mock_for_mock_setting() -> None:
    client = make_market_data_client(_settings(DATA_CLIENT="mock"))
    assert isinstance(client, MockDataClient)


def test_factory_raises_on_schwab_without_db_or_encryption() -> None:
    """Phase 8a.5: Schwab path requires db + encryption to read schwab_client."""
    settings = _settings(DATA_CLIENT="schwab")
    with pytest.raises(DataClientNotConfigured, match="db \\+ encryption"):
        make_market_data_client(settings)


def test_factory_raises_on_unknown_client() -> None:
    # Bypass Literal validation by constructing an invalid Settings via model_construct
    settings = Settings.model_construct(
        DATABASE_PATH="/tmp/x.db",
        DATA_CLIENT="bogus",  # type: ignore[arg-type]
        MOCK_SEED=42,
    )
    with pytest.raises(ValueError, match="Unknown DATA_CLIENT"):
        make_market_data_client(settings)


def test_factory_seed_propagates_to_mock() -> None:
    client = make_market_data_client(_settings(MOCK_SEED=12345))
    assert isinstance(client, MockDataClient)
    assert client._seed == 12345  # noqa: SLF001
