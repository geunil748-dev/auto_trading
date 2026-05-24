IF OBJECT_ID(N'dbo.daily_target', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_target (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        volume_ratio DECIMAL(6, 2),
        price_change DECIMAL(6, 2),
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

IF OBJECT_ID(N'dbo.trade_history', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.trade_history (
        id INT IDENTITY PRIMARY KEY,
        trade_date DATE NOT NULL,
        ticker VARCHAR(10) NOT NULL,
        order_type VARCHAR(4) NOT NULL,
        order_price DECIMAL(10, 2),
        exec_price DECIMAL(10, 2),
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
