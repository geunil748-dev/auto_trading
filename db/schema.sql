IF OBJECT_ID(N'dbo.daily_target', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_target (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        volume_ratio DECIMAL(6, 2),
        price_change DECIMAL(6, 2),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.daily_target', 'ticker_name') IS NULL
BEGIN
    ALTER TABLE dbo.daily_target ADD ticker_name NVARCHAR(100) NULL;
END;

ALTER TABLE dbo.daily_target ALTER COLUMN volume_ratio DECIMAL(12, 2) NULL;
ALTER TABLE dbo.daily_target ALTER COLUMN price_change DECIMAL(12, 2) NULL;

IF OBJECT_ID(N'dbo.listed_target_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.listed_target_snapshot (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        ticker_name NVARCHAR(100),
        price_usd DECIMAL(12, 2),
        volume_ratio DECIMAL(12, 2),
        price_change DECIMAL(12, 2),
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF OBJECT_ID(N'dbo.holding_snapshot', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.holding_snapshot (
        id INT IDENTITY PRIMARY KEY,
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
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.trade_history', 'entry_price') IS NULL
BEGIN
    ALTER TABLE dbo.trade_history ADD entry_price DECIMAL(10, 2) NULL;
END;

IF OBJECT_ID(N'dbo.fill_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.fill_history (
        id INT IDENTITY PRIMARY KEY,
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
        is_mock BIT DEFAULT 1,
        created_at DATETIME DEFAULT GETDATE()
    );
END;

IF COL_LENGTH('dbo.fill_history', 'profit_usd') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD profit_usd DECIMAL(10, 2) NULL;
END;

IF COL_LENGTH('dbo.fill_history', 'profit_rate') IS NULL
BEGIN
    ALTER TABLE dbo.fill_history ADD profit_rate DECIMAL(8, 4) NULL;
END;

IF OBJECT_ID(N'dbo.bot_log', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.bot_log (
        id INT IDENTITY PRIMARY KEY,
        log_level VARCHAR(10),
        module VARCHAR(50),
        message NVARCHAR(500),
        created_at DATETIME DEFAULT GETDATE()
    );
END;
