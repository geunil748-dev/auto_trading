IF OBJECT_ID(N'dbo.daily_target', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_target (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        opening_volume BIGINT,
        average_volume_20d BIGINT,
        volume_ratio DECIMAL(6, 2),
        price_change DECIMAL(6, 2),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo.daily_run_summary', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_run_summary (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        candidate_selection_mode VARCHAR(20) NOT NULL,
        settings_json NVARCHAR(MAX),
        realized_profit_usd DECIMAL(14, 2),
    realized_profit_rate DECIMAL(8, 4),
    eod_sell_count INT DEFAULT 0,
    cancelled_order_count INT DEFAULT 0,
    buy_fill_count INT DEFAULT 0,
    sell_fill_count INT DEFAULT 0,
    strategy_version VARCHAR(60),
    settings_snapshot_hash VARCHAR(64),
    settings_snapshot_json NVARCHAR(MAX),
    is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE(),
        updated_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.daily_run_summary', 'candidate_selection_mode') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD candidate_selection_mode VARCHAR(20) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'settings_json') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD settings_json NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'realized_profit_usd') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD realized_profit_usd DECIMAL(14, 2) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'realized_profit_rate') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD realized_profit_rate DECIMAL(8, 4) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'eod_sell_count') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD eod_sell_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_run_summary', 'cancelled_order_count') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD cancelled_order_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_run_summary', 'buy_fill_count') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD buy_fill_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_run_summary', 'sell_fill_count') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD sell_fill_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_run_summary', 'strategy_version') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD strategy_version VARCHAR(60) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'settings_snapshot_hash') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD settings_snapshot_hash VARCHAR(64) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'settings_snapshot_json') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD settings_snapshot_json NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.daily_run_summary', 'is_mock') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD is_mock BIT DEFAULT 1;

IF COL_LENGTH('dbo.daily_run_summary', 'updated_at') IS NULL
    ALTER TABLE dbo.daily_run_summary ADD updated_at DATETIME DEFAULT GETDATE();

IF OBJECT_ID(N'dbo.daily_trade_summary_report', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_trade_summary_report (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        mode VARCHAR(10) NOT NULL,
        strategy_version VARCHAR(60),
        settings_snapshot_hash VARCHAR(64),
        summary_json NVARCHAR(MAX),
        summary_text NVARCHAR(MAX),
        total_profit_usd DECIMAL(14, 2),
        total_profit_rate DECIMAL(12, 4),
        trade_count INT DEFAULT 0,
        buy_count INT DEFAULT 0,
        sell_count INT DEFAULT 0,
        win_rate DECIMAL(8, 4),
        stop_loss_count INT DEFAULT 0,
        take_profit_count INT DEFAULT 0,
        trailing_stop_count INT DEFAULT 0,
        eod_count INT DEFAULT 0,
        sample_sufficient BIT DEFAULT 0,
        created_at DATETIME DEFAULT GETDATE(),
        updated_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'strategy_version') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD strategy_version VARCHAR(60) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'settings_snapshot_hash') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD settings_snapshot_hash VARCHAR(64) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'summary_json') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD summary_json NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'summary_text') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD summary_text NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'total_profit_usd') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD total_profit_usd DECIMAL(14, 2) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'total_profit_rate') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD total_profit_rate DECIMAL(12, 4) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'trade_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD trade_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'buy_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD buy_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'sell_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD sell_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'win_rate') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD win_rate DECIMAL(8, 4) NULL;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'stop_loss_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD stop_loss_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'take_profit_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD take_profit_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'trailing_stop_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD trailing_stop_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'eod_count') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD eod_count INT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'sample_sufficient') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD sample_sufficient BIT DEFAULT 0;

IF COL_LENGTH('dbo.daily_trade_summary_report', 'created_at') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD created_at DATETIME DEFAULT GETDATE();

IF COL_LENGTH('dbo.daily_trade_summary_report', 'updated_at') IS NULL
    ALTER TABLE dbo.daily_trade_summary_report ADD updated_at DATETIME DEFAULT GETDATE();

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UQ_daily_trade_summary_report_trade_date_mode'
      AND object_id = OBJECT_ID(N'dbo.daily_trade_summary_report')
)
    CREATE UNIQUE INDEX UQ_daily_trade_summary_report_trade_date_mode
    ON dbo.daily_trade_summary_report (trade_date, mode);

IF COL_LENGTH('dbo.daily_target', 'ticker_name') IS NULL
BEGIN
    ALTER TABLE dbo.daily_target ADD ticker_name NVARCHAR(100) NULL;
END;

IF COL_LENGTH('dbo.daily_target', 'opening_volume') IS NULL
BEGIN
    ALTER TABLE dbo.daily_target ADD opening_volume BIGINT NULL;
END;

IF COL_LENGTH('dbo.daily_target', 'average_volume_20d') IS NULL
BEGIN
    ALTER TABLE dbo.daily_target ADD average_volume_20d BIGINT NULL;
END;

IF OBJECT_ID(N'dbo.KisTokenCache', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.KisTokenCache (
        id INT IDENTITY PRIMARY KEY,
        environment VARCHAR(10) NOT NULL,
        app_key_hash VARCHAR(64) NOT NULL,
        access_token NVARCHAR(2048) NOT NULL,
        token_type VARCHAR(20) NOT NULL DEFAULT 'Bearer',
        expires_at DATETIME2(0) NOT NULL,
        issued_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        last_used_at DATETIME2(0) NULL,
        created_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_KisTokenCache_environment_app_key_hash
            UNIQUE (environment, app_key_hash)
    );
END;

IF OBJECT_ID(N'dbo.listed_target_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.listed_target_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        price_usd DECIMAL(12, 2),
        opening_volume BIGINT,
        average_volume_20d BIGINT,
        volume_ratio DECIMAL(12, 2),
        price_change DECIMAL(12, 2),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.listed_target_snapshot', 'opening_volume') IS NULL
BEGIN
    ALTER TABLE dbo.listed_target_snapshot ADD opening_volume BIGINT NULL;
END;

IF COL_LENGTH('dbo.listed_target_snapshot', 'average_volume_20d') IS NULL
BEGIN
    ALTER TABLE dbo.listed_target_snapshot ADD average_volume_20d BIGINT NULL;
END;

IF OBJECT_ID(N'dbo.holding_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.holding_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        snapshot_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        quantity INT,
        average_price DECIMAL(12, 2),
        open_price DECIMAL(12, 2),
        close_price DECIMAL(12, 2),
        total_price DECIMAL(14, 2),
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.holding_snapshot', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.holding_snapshot ADD trade_date DATE NULL;
END;

EXEC(N'
UPDATE dbo.holding_snapshot
SET trade_date = snapshot_date
WHERE trade_date IS NULL;
');

IF OBJECT_ID(N'dbo.account_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.account_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        snapshot_date DATE NOT NULL,
        cash_usd DECIMAL(14, 2),
        equity_usd DECIMAL(14, 2),
        invested_usd DECIMAL(14, 2),
        open_positions INT,
        daily_profit_rate DECIMAL(8, 4),
        realized_profit_usd DECIMAL(14, 2),
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.account_snapshot', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.account_snapshot ADD trade_date DATE NULL;
END;

EXEC(N'
UPDATE dbo.account_snapshot
SET trade_date = snapshot_date
WHERE trade_date IS NULL;
');

IF OBJECT_ID(N'dbo.account_current', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.account_current (
        account_type VARCHAR(10) NOT NULL PRIMARY KEY,
        account_label NVARCHAR(30) NOT NULL,
        trade_date DATE,
        cash_usd DECIMAL(14, 2),
        equity_usd DECIMAL(14, 2),
        invested_usd DECIMAL(14, 2),
        cash_krw DECIMAL(18, 2),
        equity_krw DECIMAL(18, 2),
        open_positions INT,
        daily_profit_rate DECIMAL(8, 4),
        realized_profit_usd DECIMAL(14, 2),
        updated_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.account_current', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.account_current ADD trade_date DATE NULL;
END;

IF OBJECT_ID(N'dbo.order_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.order_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        order_date DATE NOT NULL,
        order_time VARCHAR(8),
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        side NVARCHAR(20),
        quantity INT,
        order_price DECIMAL(12, 2),
        unfilled_quantity INT,
        order_no VARCHAR(30),
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.order_snapshot', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.order_snapshot ADD trade_date DATE NULL;
END;

EXEC(N'
UPDATE dbo.order_snapshot
SET trade_date = order_date
WHERE trade_date IS NULL;
');

IF OBJECT_ID(N'dbo.runtime_setting', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.runtime_setting (
        setting_key VARCHAR(80) NOT NULL PRIMARY KEY,
        setting_value FLOAT NOT NULL,
        updated_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo.scoring', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.scoring (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        news_score DECIMAL(5, 2),
        chart_score DECIMAL(5, 2),
        total_score DECIMAL(5, 2),
        is_selected BIT DEFAULT 0,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo.news_cache', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.news_cache (
        id INT IDENTITY PRIMARY KEY,
        ticker VARCHAR(10) NOT NULL,
        title NVARCHAR(500) NOT NULL,
        summary NVARCHAR(MAX),
        url NVARCHAR(1000),
        published_at DATETIME NULL,
        source NVARCHAR(100),
        sentiment_score INT NULL,
        fetched_at DATETIME DEFAULT GETDATE(),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo.trade_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.trade_history (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        order_type VARCHAR(4) NOT NULL,
        order_price DECIMAL(10, 2),
        exec_price DECIMAL(10, 2),
        entry_price DECIMAL(10, 2),
        max_price_after_buy DECIMAL(10, 2),
        quantity INT,
        usd_krw_rate DECIMAL(10, 2),
        profit_usd DECIMAL(10, 2),
        profit_krw DECIMAL(12, 2),
        profit_rate DECIMAL(6, 2),
        exit_reason VARCHAR(20),
        entry_reason VARCHAR(80),
        entry_reason_detail NVARCHAR(500),
        strategy_version VARCHAR(60),
        settings_snapshot_hash VARCHAR(64),
        settings_snapshot_json NVARCHAR(MAX),
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.trade_history', 'entry_price') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD entry_price DECIMAL(10, 2) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'ticker_name') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD ticker_name NVARCHAR(100) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'entry_reason') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD entry_reason VARCHAR(80) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'entry_reason_detail') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD entry_reason_detail NVARCHAR(500) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'strategy_version') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD strategy_version VARCHAR(60) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'settings_snapshot_hash') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD settings_snapshot_hash VARCHAR(64) NULL;
END;

IF COL_LENGTH('dbo.trade_history', 'settings_snapshot_json') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD settings_snapshot_json NVARCHAR(MAX) NULL;
END;

IF OBJECT_ID(N'dbo.fill_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.fill_history (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        fill_date DATE NOT NULL,
        fill_time VARCHAR(8),
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        side NVARCHAR(20),
        quantity INT,
        fill_price DECIMAL(10, 2),
        fill_amount DECIMAL(12, 2),
        profit_usd DECIMAL(10, 2),
        profit_rate DECIMAL(8, 4),
        order_no VARCHAR(30),
        entry_reason VARCHAR(80),
        entry_reason_detail NVARCHAR(500),
        strategy_version VARCHAR(60),
        settings_snapshot_hash VARCHAR(64),
        settings_snapshot_json NVARCHAR(MAX),
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.fill_history', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD trade_date DATE NULL;
END;

EXEC(N'
UPDATE dbo.fill_history
SET trade_date = fill_date
WHERE trade_date IS NULL;
');

IF COL_LENGTH('dbo.fill_history', 'profit_usd') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD profit_usd DECIMAL(10, 2) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'profit_rate') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD profit_rate DECIMAL(8, 4) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'entry_reason') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD entry_reason VARCHAR(80) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'entry_reason_detail') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD entry_reason_detail NVARCHAR(500) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'strategy_version') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD strategy_version VARCHAR(60) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'settings_snapshot_hash') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD settings_snapshot_hash VARCHAR(64) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'settings_snapshot_json') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD settings_snapshot_json NVARCHAR(MAX) NULL;
END;

IF OBJECT_ID(N'dbo.entry_profit_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.entry_profit_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        entry_time VARCHAR(8) NOT NULL,
        entry_price DECIMAL(12, 4) NOT NULL,
        profit_after_5m DECIMAL(12, 6),
        profit_after_10m DECIMAL(12, 6),
        profit_after_15m DECIMAL(12, 6),
        profit_after_20m DECIMAL(12, 6),
        profit_after_30m DECIMAL(12, 6),
        profit_after_60m DECIMAL(12, 6),
        final_exit_reason VARCHAR(80),
        final_profit_rate DECIMAL(12, 6),
        strategy_version VARCHAR(60),
        created_at DATETIME DEFAULT GETDATE(),
        updated_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo._entry_datetime', N'FN') IS NULL
EXEC(N'
    CREATE FUNCTION dbo._entry_datetime(@trade_date DATE, @time_text VARCHAR(8))
    RETURNS DATETIME
    AS
    BEGIN
        DECLARE @base DATETIME = CAST(@trade_date AS DATETIME)
        DECLARE @hour INT = TRY_CONVERT(INT, LEFT(ISNULL(@time_text, ''''), 2))
        DECLARE @minute INT = TRY_CONVERT(INT, SUBSTRING(ISNULL(@time_text, ''''), 4, 2))
        DECLARE @second INT = TRY_CONVERT(INT, SUBSTRING(ISNULL(@time_text, ''''), 7, 2))
        IF @hour IS NULL OR @minute IS NULL OR @second IS NULL
            RETURN @base
        IF @hour < 12
            SET @base = DATEADD(DAY, 1, @base)
        RETURN DATEADD(SECOND, @second, DATEADD(MINUTE, @minute, DATEADD(HOUR, @hour, @base)))
    END
');

EXEC(N'
UPDATE th
SET ticker_name = COALESCE(fh.ticker_name, lts.ticker_name, dt.ticker_name)
FROM dbo.trade_history th
OUTER APPLY (
    SELECT TOP (1) ticker_name
    FROM dbo.fill_history
    WHERE ticker = th.ticker
      AND ticker_name IS NOT NULL
      AND ticker_name <> ''''
    ORDER BY fill_date DESC, created_at DESC
) fh
OUTER APPLY (
    SELECT TOP (1) ticker_name
    FROM dbo.listed_target_snapshot
    WHERE ticker = th.ticker
      AND ticker_name IS NOT NULL
      AND ticker_name <> ''''
    ORDER BY trade_date DESC, created_at DESC
) lts
OUTER APPLY (
    SELECT TOP (1) ticker_name
    FROM dbo.daily_target
    WHERE ticker = th.ticker
      AND ticker_name IS NOT NULL
      AND ticker_name <> ''''
    ORDER BY trade_date DESC, created_at DESC
) dt
WHERE (th.ticker_name IS NULL OR th.ticker_name = '''')
  AND COALESCE(fh.ticker_name, lts.ticker_name, dt.ticker_name) IS NOT NULL;
');

IF OBJECT_ID(N'dbo.bot_log', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.bot_log (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE,
        log_level VARCHAR(10),
        module VARCHAR(50),
        message NVARCHAR(500),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.bot_log', 'trade_date') IS NULL
BEGIN
    ALTER TABLE dbo.bot_log ADD trade_date DATE NULL;
END;

EXEC(N'
UPDATE dbo.bot_log
SET trade_date = CAST(created_at AS DATE)
WHERE trade_date IS NULL;
');
