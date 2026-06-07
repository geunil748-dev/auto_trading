from trading_bot import monitor_routes


def test_get_route_constants_match_monitor_endpoints() -> None:
    assert monitor_routes.GET_HEALTH == "/health"
    assert monitor_routes.GET_STATE == "/api/state"
    assert monitor_routes.GET_HISTORY == "/api/history"
    assert monitor_routes.GET_DAILY_SUMMARY == "/api/daily-summary"
    assert monitor_routes.GET_DAILY_SUMMARY_DETAIL == "/api/daily-summary/detail"
    assert monitor_routes.GET_TRADING_SETTINGS == "/api/trading-settings"
    assert monitor_routes.GET_MANUAL_SCREENING == "/api/manual-screening"
    assert monitor_routes.GET_BACKTEST == "/api/backtest"
    assert monitor_routes.INDEX_PATH == "/"
    assert monitor_routes.INDEX_FILE == "/index.html"


def test_post_route_constants_match_monitor_endpoints() -> None:
    assert monitor_routes.POST_REAL_TRADING_CONTROL == "/api/real-trading-control"
    assert monitor_routes.POST_MANUAL_MOCK_SELL == "/api/manual-mock-sell"
    assert monitor_routes.POST_MANUAL_MOCK_SELL_ALL == "/api/manual-mock-sell-all"
    assert monitor_routes.POST_MANUAL_SCREENING == "/api/manual-screening"
    assert monitor_routes.POST_DAILY_SUMMARY_GENERATE == "/api/daily-summary/generate"
    assert monitor_routes.POST_TRADING_SETTINGS == "/api/trading-settings"
