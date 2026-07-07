from types import SimpleNamespace

from trading_bot.config import APP_MODE_REAL, KisSettings, TradingSettings
from trading_bot import composition_mock, composition_real


def _kis_settings() -> KisSettings:
    return KisSettings("app", "secret", "12345678", "01", "https://kis.example")


def test_mock_composition_uses_mock_account_for_shared_dry_run(monkeypatch) -> None:
    captured = {}

    def fake_build(
        settings,
        kis_settings,
        *,
        account_mock,
        repository=None,
        candidate_notification_sender=None,
    ):
        captured["account_mock"] = account_mock
        captured["repository"] = repository
        return "runtime", "repository"

    monkeypatch.setattr(composition_mock, "build_kis_live_dry_run", fake_build)

    assert composition_mock.build_live_dry_run(TradingSettings(), _kis_settings()) == (
        "runtime",
        "repository",
    )
    assert captured["account_mock"] is True
    assert captured["repository"] is None


def test_real_composition_uses_real_account_for_shared_dry_run(monkeypatch) -> None:
    captured = {}

    def fake_build(
        settings,
        kis_settings,
        *,
        account_mock,
        repository=None,
        candidate_notification_sender=None,
    ):
        captured["account_mock"] = account_mock
        captured["repository"] = repository
        return "runtime", "repository"

    monkeypatch.setattr(composition_real, "build_kis_live_dry_run", fake_build)

    assert composition_real.build_real_live_dry_run(
        TradingSettings(app_mode=APP_MODE_REAL),
        _kis_settings(),
    ) == ("runtime", "repository")
    assert captured["account_mock"] is False
    assert captured["repository"].__class__.__name__ == "ReadOnlyDailyRepository"


def test_real_composition_builds_disabled_real_executor(monkeypatch) -> None:
    captured = {}

    class FakeRealSubmitter:
        def __init__(self, *args, **kwargs) -> None:
            captured.update(kwargs)

        def submit(self, intent):
            return {"ok": True}

    monkeypatch.setattr(composition_real, "KisJsonClient", lambda settings: "json")
    monkeypatch.setattr(
        composition_real,
        "KisOverseasClient",
        lambda client: SimpleNamespace(quote=lambda ticker: None),
    )
    monkeypatch.setattr(
        composition_real,
        "load_real_trading_control",
        lambda settings: SimpleNamespace(manual_enabled=True),
    )
    monkeypatch.setattr(composition_real, "KisRealBuySubmitter", FakeRealSubmitter)

    executor = composition_real.build_real_buy_executor(
        _kis_settings(),
        repository=object(),
        settings=TradingSettings(app_mode=APP_MODE_REAL),
    )

    assert executor.mock is False
    assert captured["manual_enabled"] is True
    assert captured["allow_real_api_call"] is False
