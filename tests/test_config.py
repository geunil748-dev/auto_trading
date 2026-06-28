import pytest

from trading_bot.config import (
    load_kis_settings,
    load_notification_settings,
    load_real_kis_settings,
    load_settings,
    runtime_risk_settings_payload,
    save_runtime_risk_settings,
)


@pytest.fixture(autouse=True)
def _isolate_local_dotenv(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)


def test_load_real_kis_settings_uses_dedicated_real_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_PRODUCT", "01")
    monkeypatch.setenv("KIS_REAL_BASE_URL", "https://real.example")

    settings = load_real_kis_settings()

    assert settings.app_key == "real-key"
    assert settings.app_secret == "real-secret"
    assert settings.account_no == "12345678"
    assert settings.account_product == "01"
    assert settings.base_url == "https://real.example"


def test_load_settings_keeps_real_trading_locked_by_default(monkeypatch) -> None:
    monkeypatch.delenv("APP_MODE", raising=False)
    monkeypatch.delenv("REAL_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("REAL_EMERGENCY_STOP", raising=False)

    settings = load_settings()

    assert settings.app_mode == "test"
    assert settings.real_trading_enabled is False
    assert settings.real_emergency_stop is True
    assert settings.real_max_order_krw == 100000
    assert settings.real_max_daily_order_krw == 300000


def test_load_settings_reads_real_trading_safety_limits(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")
    monkeypatch.setenv("REAL_MAX_ORDER_KRW", "50000")
    monkeypatch.setenv("REAL_MAX_DAILY_ORDER_KRW", "150000")

    settings = load_settings()

    assert settings.real_trading_enabled is True
    assert settings.real_emergency_stop is False
    assert settings.real_max_order_krw == 50000
    assert settings.real_max_daily_order_krw == 150000


def test_load_settings_test_mode_ignores_real_trading_unlock(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")

    settings = load_settings()

    assert settings.app_mode == "test"
    assert settings.real_trading_enabled is False
    assert settings.real_emergency_stop is True


def test_load_settings_allows_market_ma20_bypass_only_in_test_mock_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("MOCK_TRADING", "true")
    monkeypatch.setenv("ALLOW_MARKET_BELOW_MA20_BYPASS", "true")

    settings = load_settings()

    assert settings.allow_market_below_ma20_bypass is True
    assert runtime_risk_settings_payload(settings)["allowMarketBelowMa20Bypass"] is True


def test_load_settings_forces_market_ma20_bypass_off_in_real_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("MOCK_TRADING", "true")
    monkeypatch.setenv("ALLOW_MARKET_BELOW_MA20_BYPASS", "true")

    settings = load_settings()

    assert settings.allow_market_below_ma20_bypass is False


def test_load_settings_forces_market_ma20_bypass_off_when_mock_trading_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("MOCK_TRADING", "false")
    monkeypatch.setenv("ALLOW_MARKET_BELOW_MA20_BYPASS", "true")

    settings = load_settings()

    assert settings.allow_market_below_ma20_bypass is False


def test_load_settings_rejects_invalid_app_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "prod")

    with pytest.raises(ValueError, match="APP_MODE"):
        load_settings()


def test_real_kis_settings_require_real_app_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "test")

    with pytest.raises(ValueError, match="APP_MODE=real"):
        load_real_kis_settings()


def test_test_app_mode_rejects_official_real_kis_url(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
    monkeypatch.setenv("KIS_APP_KEY", "mock-key")
    monkeypatch.setenv("KIS_APP_SECRET", "mock-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")

    with pytest.raises(ValueError, match="APP_MODE=test"):
        load_kis_settings()


def test_load_settings_reads_ranking_limits(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("GAINER_RANKING_LIMIT", "240")
    monkeypatch.setenv("TURNOVER_RANKING_LIMIT", "260")
    monkeypatch.setenv("INITIAL_RANKED_EVALUATION_LIMIT", "45")
    monkeypatch.setenv("RANKED_EVALUATION_BATCH_SIZE", "15")
    monkeypatch.setenv("MAX_RANKED_EVALUATION_CANDIDATES", "95")
    monkeypatch.setenv("TARGET_FILTERED_CANDIDATES", "21")
    monkeypatch.setenv("CANDIDATE_EVAL_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("RANKING_SELECTION_MODE", "composite")

    settings = load_settings()

    assert settings.gainer_ranking_limit == 240
    assert settings.turnover_ranking_limit == 260
    assert settings.ranking_selection_mode == "composite"
    assert settings.initial_ranked_evaluation_limit == 45
    assert settings.ranked_evaluation_batch_size == 15
    assert settings.max_ranked_evaluation_candidates == 95
    assert settings.target_filtered_candidates == 21
    assert settings.candidate_eval_timeout_seconds == 90
    assert runtime_risk_settings_payload(settings)["rankingSelectionMode"] == "composite"


def test_load_settings_reads_manual_buy_list_options(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MANUAL_BUY_LIST_ENABLED", "false")
    monkeypatch.setenv("MANUAL_BUY_LIST_PATH", "monitor/custom_manual.json")
    monkeypatch.setenv("MAX_MANUAL_BUY_TICKERS", "12")
    monkeypatch.setenv("MAX_MANUAL_SELECTED_CANDIDATES", "4")

    settings = load_settings()

    assert settings.manual_buy_list_enabled is False
    assert settings.manual_buy_list_path == "monitor/custom_manual.json"
    assert settings.max_manual_buy_tickers == 12
    assert settings.max_manual_selected_candidates == 4


def test_load_settings_rejects_invalid_ranking_selection_mode(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("RANKING_SELECTION_MODE", "unknown")

    with pytest.raises(ValueError, match="RANKING_SELECTION_MODE"):
        load_settings()


def test_load_settings_defaults_to_fixed_candidate_watch(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
        "REFRESH_INTRADAY_CANDIDATES",
        "CANDIDATE_SELECTION_MODE",
    ):
        monkeypatch.setenv(name, "")

    settings = load_settings()

    assert settings.refresh_intraday_candidates is False
    assert settings.candidate_selection_mode == "fixed"
    assert settings.ranking_selection_mode == "intersection"
    assert runtime_risk_settings_payload(settings)["refreshIntradayCandidates"] is False
    assert runtime_risk_settings_payload(settings)["candidateSelectionMode"] == "fixed"
    assert runtime_risk_settings_payload(settings)["rankingSelectionMode"] == "intersection"


def test_load_settings_defaults_vwap_ma20_condition_off(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
        "REQUIRE_VWAP_OR_MA20",
        "VWAP_MA20_CONDITION_MODE",
        "VWAP_MA20_CONDITION_TYPE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()
    payload = runtime_risk_settings_payload(settings)

    assert settings.require_vwap_or_ma20 is False
    assert settings.vwap_ma20_condition_mode == "HARD_FILTER"
    assert settings.vwap_ma20_condition_type == "OR"
    assert payload["requireVwapOrMa20"] is False
    assert payload["vwapMa20ConditionMode"] == "HARD_FILTER"
    assert payload["vwapMa20ConditionType"] == "OR"


def test_load_settings_uses_candidate_collection_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
        "MIN_PRICE_USD",
        "MAX_PRICE_USD",
        "GAINER_RANKING_LIMIT",
        "TURNOVER_RANKING_LIMIT",
        "MIN_TOTAL_SCORE",
        "MIN_OPENING_PRICE_CHANGE",
        "MIN_VOLUME_RATIO",
        "MAX_OPENING_GAP",
        "MIN_5M_VOLUME_INCREASE_PERCENT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.min_price_usd == 10
    assert settings.max_price_usd == 300
    assert settings.gainer_ranking_limit == 100
    assert settings.turnover_ranking_limit == 100
    assert settings.initial_ranked_evaluation_limit == 50
    assert settings.ranked_evaluation_batch_size == 25
    assert settings.max_ranked_evaluation_candidates == 125
    assert settings.target_filtered_candidates == 15
    assert settings.candidate_eval_timeout_seconds == 120.0
    assert settings.min_total_score == 60
    assert settings.min_opening_price_change == 0.0
    assert settings.min_volume_ratio == 1.0
    assert settings.max_opening_gap == 0.30
    assert settings.max_entry_price_change == 0.10
    assert settings.breakout_hold_minutes == 1.0
    assert settings.min_5m_volume_increase_percent == 5.0
    assert runtime_risk_settings_payload(settings)["minTotalScore"] == 60
    assert runtime_risk_settings_payload(settings)["maxEntryPriceChangePercent"] == 10.0
    assert runtime_risk_settings_payload(settings)["breakoutHoldMinutes"] == 1.0
    assert runtime_risk_settings_payload(settings)["min5mVolumeIncreasePercent"] == 5.0
    assert runtime_risk_settings_payload(settings)["initialRankedEvaluationLimit"] == 50
    assert runtime_risk_settings_payload(settings)["rankedEvaluationBatchSize"] == 25
    assert runtime_risk_settings_payload(settings)["maxRankedEvaluationCandidates"] == 125
    assert runtime_risk_settings_payload(settings)["targetFilteredCandidates"] == 15
    assert runtime_risk_settings_payload(settings)["candidateEvalTimeoutSeconds"] == 120.0


def test_load_settings_scales_target_filtered_candidates_from_selected_limit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
        "TARGET_FILTERED_CANDIDATES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAX_SELECTED_CANDIDATES", "8")

    settings = load_settings()

    assert settings.max_selected_candidates == 8
    assert settings.target_filtered_candidates == 24


@pytest.mark.parametrize(
    ("name", "value", "match"),
    (
        ("MAX_SELECTED_CANDIDATES", "0", "MAX_SELECTED_CANDIDATES"),
        ("RANKED_EVALUATION_BATCH_SIZE", "0", "RANKED_EVALUATION_BATCH_SIZE"),
        ("CANDIDATE_EVAL_TIMEOUT_SECONDS", "0", "CANDIDATE_EVAL_TIMEOUT_SECONDS"),
    ),
)
def test_load_settings_rejects_invalid_candidate_evaluation_values(
    tmp_path,
    monkeypatch,
    name: str,
    value: str,
    match: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    for env_name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=match):
        load_settings()


def test_load_settings_rejects_initial_evaluation_limit_above_max(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    for env_name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("INITIAL_RANKED_EVALUATION_LIMIT", "126")
    monkeypatch.setenv("MAX_RANKED_EVALUATION_CANDIDATES", "125")

    with pytest.raises(ValueError, match="INITIAL_RANKED_EVALUATION_LIMIT"):
        load_settings()


def test_load_settings_continues_when_runtime_settings_db_save_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    monkeypatch.setattr("trading_bot.config._read_runtime_settings_from_db", lambda: {})

    for key, value in {
        "MSSQL_HOST": "localhost",
        "MSSQL_DATABASE": "trading",
        "MSSQL_USERNAME": "user",
        "MSSQL_PASSWORD": "password",
    }.items():
        monkeypatch.setenv(key, value)

    def broken_save(payload: dict[str, float]) -> bool:
        raise RuntimeError("No module named 'clr'")

    monkeypatch.setattr("trading_bot.config._save_runtime_settings_to_db", broken_save)

    settings = load_settings()

    assert settings.min_price_usd == 10
    assert not (tmp_path / "monitor" / "trading_settings.json").exists()


def test_load_settings_reads_unfilled_reorder_policies(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_UNFILLED_REORDER_MINUTES", "2")
    monkeypatch.setenv("MOCK_UNFILLED_REORDER_LIMIT", "1")
    monkeypatch.setenv("REAL_UNFILLED_REORDER_MINUTES", "1")

    settings = load_settings()

    assert settings.mock_unfilled_reorder_minutes == 2
    assert settings.mock_unfilled_reorder_limit == 1
    assert settings.real_unfilled_reorder_minutes == 1


def test_load_settings_reads_p1_stability_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STOP_LOSS_COOLDOWN_MINUTES", "45")
    monkeypatch.setenv("MAX_CONSECUTIVE_STOP_LOSS_COUNT", "4")
    monkeypatch.setenv("MAX_BID_ASK_SPREAD_RATE", "1.5")
    monkeypatch.setenv("MAX_EXPECTED_FILL_PRICE_GAP_RATE", "2.5")
    monkeypatch.setenv("MAX_ORDER_RETRY_COUNT", "3")
    monkeypatch.setenv("ORDER_RETRY_DELAY_SECONDS", "5")
    monkeypatch.setenv("PARTIAL_FILL_POLICY", "CANCEL_REMAINING")
    monkeypatch.setenv("UNFILLED_CANCEL_AFTER_SECONDS", "90")

    settings = load_settings()

    assert settings.stop_loss_cooldown_minutes == 45
    assert settings.max_consecutive_stop_loss_count == 4
    assert settings.max_bid_ask_spread_rate == 1.5
    assert settings.max_expected_fill_price_gap_rate == 2.5
    assert settings.max_order_retry_count == 3
    assert settings.order_retry_delay_seconds == 5
    assert settings.partial_fill_policy == "CANCEL_REMAINING"
    assert settings.unfilled_cancel_after_seconds == 90


def test_load_settings_keeps_current_strategy_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STRATEGY_PRESET", "current")
    monkeypatch.setenv("TAKE_PROFIT_RATE", "0.05")
    monkeypatch.setenv("TRAILING_STOP_ACTIVATION_RATE", "0.03")
    monkeypatch.setenv("ALLOW_RELAXED_CANDIDATE_FILTER", "true")
    monkeypatch.setenv("ENABLE_PYRAMIDING", "false")

    settings = load_settings()

    assert settings.strategy_preset == "current"
    assert settings.max_position_loss == -0.03
    assert settings.take_profit_rate == 0.05
    assert settings.trailing_stop_activation_rate == 0.03
    assert settings.trailing_stop_drop == 0.015
    assert settings.allow_relaxed_candidate_filter is True
    assert settings.enable_pyramiding is False


def test_load_settings_applies_conservative_intraday_preset(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STRATEGY_PRESET", "conservative_intraday")
    monkeypatch.setenv("TAKE_PROFIT_RATE", "0.05")
    monkeypatch.setenv("TRAILING_STOP_ACTIVATION_RATE", "0.03")

    settings = load_settings()

    assert settings.strategy_preset == "conservative_intraday"
    assert settings.max_position_loss == -0.025
    assert settings.take_profit_rate == 0.03
    assert settings.trailing_stop_activation_rate == 0.02
    assert settings.trailing_stop_drop == 0.015


def test_load_settings_applies_balanced_intraday_preset(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STRATEGY_PRESET", "balanced_intraday")
    monkeypatch.setenv("RELAX_OPENING_CHANGE_ONLY", "true")

    settings = load_settings()

    assert settings.strategy_preset == "balanced_intraday"
    assert settings.max_position_loss == -0.035
    assert settings.take_profit_rate == 0.04
    assert settings.trailing_stop_activation_rate == 0.025
    assert settings.trailing_stop_drop == 0.02
    assert settings.relax_opening_change_only is True


def test_load_notification_settings_reads_optional_alert_channels(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_DISCORD_WEBHOOK_URL", "https://discord.example")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "1234")

    settings = load_notification_settings()

    assert settings.discord_webhook_url == "https://discord.example"
    assert settings.telegram_bot_token == "telegram-token"
    assert settings.telegram_chat_id == "1234"


def test_runtime_risk_settings_override_env_values(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    save_runtime_risk_settings(
        7.5,
        12.0,
        40,
        10,
        120,
        1.5,
        0.8,
        25,
        False,
        "hybrid",
        False,
        4,
        22,
        3,
        True,
        True,
        True,
        True,
        220,
        230,
    )

    settings = load_settings()

    assert settings.max_position_loss == -0.075
    assert settings.take_profit_rate == 0.12
    assert settings.min_total_score == 40
    assert settings.min_price_usd == 10
    assert settings.max_price_usd == 120
    assert settings.min_opening_price_change == 0.015
    assert settings.min_volume_ratio == 0.8
    assert settings.max_opening_gap == 0.25
    assert settings.gainer_ranking_limit == 220
    assert settings.turnover_ranking_limit == 230
    assert settings.partial_take_profit_enabled is False
    assert settings.trailing_stop_activation_rate == 0.04
    assert settings.refresh_intraday_candidates is True
    assert settings.candidate_selection_mode == "hybrid"
    assert runtime_risk_settings_payload(settings)["stopLossPercent"] == 7.5
    assert runtime_risk_settings_payload(settings)["minTotalScore"] == 40
    assert runtime_risk_settings_payload(settings)["minOpeningPriceChangePercent"] == 1.5
    assert runtime_risk_settings_payload(settings)["maxOpeningGapPercent"] == 25
    assert runtime_risk_settings_payload(settings)["gainerRankingLimit"] == 220
    assert runtime_risk_settings_payload(settings)["turnoverRankingLimit"] == 230
    assert runtime_risk_settings_payload(settings)["refreshIntradayCandidates"] is True
    assert runtime_risk_settings_payload(settings)["candidateSelectionMode"] == "hybrid"
    assert runtime_risk_settings_payload(settings)["partialTakeProfitEnabled"] is False
    assert runtime_risk_settings_payload(settings)["trailingStopActivationPercent"] == 4
    assert runtime_risk_settings_payload(settings)["maxEntryPriceChangePercent"] == 22
    assert runtime_risk_settings_payload(settings)["breakoutHoldMinutes"] == 3
    assert runtime_risk_settings_payload(settings)["require5mCloseAboveBreakout"] is True
    assert runtime_risk_settings_payload(settings)["require5mVolumeIncrease"] is True
    assert runtime_risk_settings_payload(settings)["requireVwapOrMa20"] is True
    assert runtime_risk_settings_payload(settings)["requirePullbackRebreak"] is True
    assert runtime_risk_settings_payload(settings)["strategyPreset"] == "current"
    assert runtime_risk_settings_payload(settings)["allowRelaxedCandidateFilter"] is True
    assert runtime_risk_settings_payload(settings)["enablePyramiding"] is False


def test_runtime_risk_settings_rejects_min_price_below_ten(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")

    try:
        save_runtime_risk_settings(
            5,
            10,
            min_price_usd=9.99,
            max_price_usd=150,
        )
    except ValueError as exc:
        assert "최저 가격은 10 이상" in str(exc)
    else:
        raise AssertionError("min_price_usd below 10 must be rejected")


def test_runtime_risk_settings_persist_condition_modes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")

    save_runtime_risk_settings(
        5,
        10,
        overheat_limit_condition_mode="HARD_FILTER",
        breakout_close_condition_mode="SOFT_SCORE",
        volume_increase_condition_mode="LOG_ONLY",
        min_5m_volume_increase_percent=7.5,
        vwap_ma20_condition_mode="HARD_FILTER",
        vwap_ma20_condition_type="AND",
        pullback_rebreak_condition_mode="OFF",
    )

    settings = load_settings()
    payload = runtime_risk_settings_payload(settings)

    assert settings.breakout_close_condition_mode == "SOFT_SCORE"
    assert settings.volume_increase_condition_mode == "LOG_ONLY"
    assert settings.min_5m_volume_increase_percent == 7.5
    assert settings.vwap_ma20_condition_mode == "HARD_FILTER"
    assert settings.vwap_ma20_condition_type == "AND"
    assert settings.pullback_rebreak_condition_mode == "OFF"
    assert payload["breakoutCloseConditionMode"] == "SOFT_SCORE"
    assert payload["volumeIncreaseConditionMode"] == "LOG_ONLY"
    assert payload["min5mVolumeIncreasePercent"] == 7.5
    assert payload["vwapMa20ConditionType"] == "AND"
