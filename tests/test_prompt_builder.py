"""Prompt builder tests — substitution, truncation, budget guard."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shared.clients.exa_news import ExaArticle
from shared.clients.mock_exa_news import MockExaClient
from shared.services.prompt_builder import (
    PromptTooLargeError,
    build_entry_prompt,
    build_exit_prompt,
)
from shared.services.prompts import create_prompt_version
from shared.strategy.settings import EvaluatorSettings


@pytest.fixture
async def db_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "pb.db"))
    import importlib

    from shared import config as cfg
    importlib.reload(cfg)
    from shared import db as db_mod
    importlib.reload(db_mod)
    db_mod.run_migrations()
    conn = db_mod.get_connection()
    yield conn
    conn.close()


async def test_entry_prompt_substitutes_all_keys(db_conn) -> None:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    exa = MockExaClient(auto_seed=False)
    rendered, version, articles = await build_entry_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    # Active prompt seeded by migration is entry v1.
    assert version.template_name == "entry_evaluation"
    assert "{ticker}" not in rendered  # all subs applied
    assert cand.ticker in rendered
    assert isinstance(articles, list)


async def test_entry_prompt_truncates_shortlist_to_5(db_conn) -> None:
    from tests.fixtures.strategy_fixtures import (
        build_long_call_candidate,
        make_option_contract,
    )

    cand = await build_long_call_candidate()
    cand.shortlist = [
        make_option_contract(
            symbol=f"NVDA250620C{150 + i}", strike=Decimal(str(150 + i))
        )
        for i in range(10)
    ]
    exa = MockExaClient(auto_seed=False)
    rendered, _, _ = await build_entry_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    # Each contract in the shortlist JSON has the unique field "underlying_spot".
    count = rendered.count('"underlying_spot"')
    assert count <= 5


async def test_entry_prompt_includes_news_articles(db_conn) -> None:
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    exa = MockExaClient(auto_seed=False)
    exa.inject_article(
        cand.ticker,
        ExaArticle(
            title="Major catalyst announced",
            url="https://news.example.com/catalyst",
            published_date=datetime.now(UTC),
            summary="The big one.",
        ),
    )
    rendered, _, articles = await build_entry_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    assert len(articles) >= 1
    assert "Major catalyst announced" in rendered


async def test_oversized_prompt_raises(db_conn) -> None:
    """Force a tiny token budget so the seeded prompt overflows."""
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    exa = MockExaClient(auto_seed=False)
    cfg = EvaluatorSettings(prompt_token_budget=10)  # 10 * 4 = 40 chars
    with pytest.raises(PromptTooLargeError):
        await build_entry_prompt(cand, db_conn, exa, cfg)


async def test_different_versions_produce_different_output(db_conn) -> None:
    from shared.services.prompts import activate_prompt_version
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    cand = await build_long_call_candidate()
    exa = MockExaClient(auto_seed=False)
    rendered_v1, version_v1, _ = await build_entry_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    v2 = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text=(
            "DIFFERENT-V2-PROMPT ticker={ticker} direction={direction} "
            "confidence={confidence} rule_trace={rule_trace} "
            "full_analysis={full_analysis} options_analysis={options_analysis} "
            "regime={regime} shortlist={shortlist} "
            "calendar_context={calendar_context} exa_articles={exa_articles}"
        ),
        response_schema={"type": "object", "required": ["decision"]},
        created_by="test",
    )
    await activate_prompt_version(db_conn, v2.id)
    rendered_v2, version_v2, _ = await build_entry_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    assert version_v1.id != version_v2.id
    assert "DIFFERENT-V2-PROMPT" in rendered_v2
    assert rendered_v1 != rendered_v2


async def test_missing_template_var_raises_keyerror(db_conn) -> None:
    """Inject a v2 prompt referencing a non-existent var and verify KeyError."""
    from shared.services.prompts import activate_prompt_version
    from tests.fixtures.strategy_fixtures import build_long_call_candidate

    v2 = await create_prompt_version(
        db_conn,
        template_name="entry_evaluation",
        template_text="ticker={ticker} mystery={does_not_exist}",
        response_schema={"type": "object", "required": ["decision"]},
        created_by="test",
    )
    await activate_prompt_version(db_conn, v2.id)
    cand = await build_long_call_candidate()
    exa = MockExaClient(auto_seed=False)
    with pytest.raises(KeyError):
        await build_entry_prompt(cand, db_conn, exa, EvaluatorSettings())


async def test_exit_prompt_substitutes_position_context(db_conn) -> None:
    from tests.fixtures.strategy_fixtures import build_exit_candidate

    cand = build_exit_candidate()
    db_conn.execute(
        "INSERT INTO positions (id, ticker, contract_symbol, side, quantity, "
        "entry_price, entry_ts, status) VALUES (?, ?, ?, 'long', 1, 5.0, ?, 'open')",
        (
            cand.position_id,
            cand.ticker,
            "NVDA250620C150",
            datetime.now(UTC).timestamp() - 3600,
        ),
    )
    db_conn.commit()
    exa = MockExaClient(auto_seed=False)
    rendered, version, _ = await build_exit_prompt(
        cand, db_conn, exa, EvaluatorSettings()
    )
    assert version.template_name == "exit_evaluation"
    assert "NVDA250620C150" in rendered
    assert str(cand.position_id) in rendered
    assert "{ticker}" not in rendered
