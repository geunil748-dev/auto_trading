import json

from trading_bot.config import TradingSettings
from trading_bot.strategy_metadata import strategy_metadata_from_settings


def test_intraday_missing_data_policy_changes_settings_snapshot_hash() -> None:
    log_only = strategy_metadata_from_settings(
        TradingSettings(intraday_missing_data_policy="LOG_ONLY")
    )
    block = strategy_metadata_from_settings(
        TradingSettings(intraday_missing_data_policy="BLOCK")
    )

    assert json.loads(log_only.settings_snapshot_json)[
        "intradayMissingDataPolicy"
    ] == "LOG_ONLY"
    assert json.loads(block.settings_snapshot_json)["intradayMissingDataPolicy"] == "BLOCK"
    assert log_only.settings_snapshot_hash != block.settings_snapshot_hash


def test_real_snapshot_forces_requested_log_only_policy_to_block() -> None:
    metadata = strategy_metadata_from_settings(
        TradingSettings(
            app_mode="real",
            mock_trading=False,
            intraday_missing_data_policy="LOG_ONLY",
        )
    )

    assert json.loads(metadata.settings_snapshot_json)[
        "intradayMissingDataPolicy"
    ] == "BLOCK"
