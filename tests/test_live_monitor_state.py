from datetime import datetime, timezone

from trading_bot.live_monitor_state import live_kis_monitor_state
from trading_bot.models import AccountState
from trading_bot.config import KisSettings


class Accounts:
    def current_account(self) -> AccountState:
        return AccountState(97000, 99000, 2000, 2, 0)

    def holdings(self) -> list[dict[str, str]]:
        return [
            {
                "ticker": "AAA",
                "name": "Alpha",
                "quantity": "2",
                "openPrice": "$11.10",
                "closePrice": "$11.60",
            }
        ]


class Kis:
    def mock_order_history(self, account_no: str, account_product: str, day: str):
        assert (account_no, account_product, day) == ("12345678", "01", "20260522")
        return [
            {
                "ord_tmd": "230818",
                "pdno": "AAA",
                "prdt_name": "Alpha",
                "sll_buy_dvsn_cd_name": "매수",
                "ft_ord_qty": "2",
                "ft_ord_unpr3": "10.50",
                "ft_ccld_qty": "2",
                "ft_ccld_unpr3": "10.50",
                "ft_ccld_amt3": "21.00",
                "nccs_qty": "0",
            }
        ]


def test_live_monitor_state_shapes_orders_fills_and_holdings() -> None:
    state = live_kis_monitor_state(
        Kis(),
        Accounts(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
        now=datetime(2026, 5, 22, 16, tzinfo=timezone.utc),
    )

    assert state["holdings"] == [
        {
            "ticker": "AAA",
            "name": "Alpha",
            "quantity": "2",
            "openPrice": "$11.10",
            "closePrice": "$11.60",
        }
    ]
    assert state["targets"] == [["AAA", "$10.50", "-", "-", "-", "주문 접수"]]
    assert state["account"]["cashUsd"] == "$97,000.00"
    assert state["account"]["equityUsd"] == "$99,000.00"
    assert state["orders"][0]["ticker"] == "AAA"
    assert state["fills"][0]["total"] == "$21.00"
    assert state["logs"] == [["230818", "주문", "AAA 매수 2주 시도"]]
