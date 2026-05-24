from trading_bot.config import KisSettings
from trading_bot.dashboard_state import _real_krw_summary


class Http:
    def __init__(self, settings: KisSettings) -> None:
        self.settings = settings


class Domestic:
    def __init__(self, http: Http) -> None:
        self.http = http

    def balance(self, account_no: str, account_product: str) -> dict[str, object]:
        assert (account_no, account_product) == ("12345678", "01")
        return {
            "output2": [
                {
                    "dnca_tot_amt": "100000",
                    "tot_evlu_amt": "125000",
                }
            ]
        }


def test_real_krw_summary_maps_domestic_balance(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.dashboard_state.KisJsonClient", Http)
    monkeypatch.setattr("trading_bot.dashboard_state.KisDomesticClient", Domestic)

    summary = _real_krw_summary(
        KisSettings("app", "secret", "12345678", "01", "https://kis.test")
    )

    assert summary == {
        "cashKrw": "100,000원",
        "equityKrw": "125,000원",
    }
