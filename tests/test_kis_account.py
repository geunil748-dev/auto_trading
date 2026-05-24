from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.config import KisSettings
from trading_bot.models import PositionState


def test_kis_account_reader_combines_balance_and_buyable_amount() -> None:
    class Kis:
        def balance(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {
                "output1": [
                    {
                        "ovrs_stck_evlu_amt": "1200.00",
                        "frcr_pchs_amt1": "1000.00",
                        "ovrs_cblc_qty": "10",
                    },
                    {
                        "ovrs_stck_evlu_amt": "300.00",
                        "frcr_pchs_amt1": "500.00",
                        "ovrs_cblc_qty": "0",
                    },
                ],
                "output2": {"tot_pftrt": "-1.25"},
            }

        def buyable_amount(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {"output": {"ord_psbl_frcr_amt": "2,500.00"}}

    account = KisAccountReader(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).current_account()

    assert account.cash_usd == 2500
    assert account.equity_usd == 4000
    assert account.invested_usd == 1500
    assert account.open_positions == 1
    assert account.daily_profit_rate == -0.0125


def test_kis_account_reader_maps_positions_from_balance_rows() -> None:
    class Kis:
        def balance(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {
                "output1": [
                    {
                        "ovrs_pdno": "AAA",
                        "ovrs_cblc_qty": "2",
                        "pchs_avg_pric": "10.00",
                        "now_pric2": "11.50",
                    },
                    {"ovrs_pdno": "ZERO", "ovrs_cblc_qty": "0"},
                ]
            }

    positions = KisAccountReader(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).positions()

    assert positions == [PositionState("AAA", 10, 2, 11.5, 11.5)]


def test_kis_account_reader_maps_monitor_holdings_from_balance_rows() -> None:
    class Kis:
        def balance(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {
                "output1": [
                    {
                        "ovrs_pdno": "AAA",
                        "ovrs_item_name": "Alpha",
                        "ovrs_cblc_qty": "2",
                        "pchs_avg_pric": "10.00",
                        "ovrs_stck_evlu_amt": "23.00",
                    }
                ]
            }

    holdings = KisAccountReader(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).holdings()

    assert holdings == [
        {
            "ticker": "AAA",
            "name": "Alpha",
            "quantity": "2",
            "averagePrice": "$10.00",
            "openPrice": "-",
            "closePrice": "-",
            "totalPrice": "$23.00",
        }
    ]


def test_kis_account_reader_adds_session_prices_to_monitor_holdings() -> None:
    class Kis:
        def balance(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {
                "output1": [
                    {
                        "ovrs_pdno": "AAA",
                        "ovrs_item_name": "Alpha",
                        "ovrs_cblc_qty": "2",
                        "pchs_avg_pric": "10.00",
                        "ovrs_stck_evlu_amt": "23.00",
                    }
                ]
            }

        def quote(self, ticker: str) -> dict[str, str]:
            assert ticker == "AAA"
            return {"last": "11.75"}

        def daily_prices(self, ticker: str) -> list[dict[str, str]]:
            assert ticker == "AAA"
            return [{"open": "11.10", "clos": "11.60"}]

    holdings = KisAccountReader(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).holdings()

    assert holdings[0]["openPrice"] == "$11.10"
    assert holdings[0]["closePrice"] == "$11.60"
