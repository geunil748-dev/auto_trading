# 운영 데이터 엑셀 리포트 스펙

## 목적

운영 DB에 쌓인 후보, 점수, 후보 평가, 주문, 체결, 손익, 로그 데이터를 read-only로 조회해 사람이 검토할 수 있는 엑셀 리포트와 runner 분석 산출물을 만든다. 이 문서는 "2주 데이터 엑셀로 정리", "운영 데이터 리뷰", "runner 분석" 요청의 기본 형식을 정의한다.

## 기본 원칙

- read-only SELECT만 수행한다.
- 코드 수정, 커밋, PR 생성은 하지 않는다.
- DB INSERT / UPDATE / DELETE / ALTER 금지.
- KIS API, 주문 API, Telegram API 호출 금지.
- scheduler / monitor 재시작 금지.
- `.env`, 토큰, appkey, appsecret, 계좌번호 원문 출력 금지.
- 계좌번호나 민감값은 마스킹한다.
- 분석 산출물은 `reports/analysis/`에 저장하되 커밋하지 않는다.
- `reports/analysis/*`와 `.codex-remote-attachments/*`는 문서 예시로만 참고하고 커밋하지 않는다.

## 파일명 규칙

- 기본 엑셀 파일: `reports/analysis/auto_trading_review_YYYY-MM-DD.xlsx`
- 날짜는 생성일 또는 분석 종료일 기준으로 쓴다.
- runner 분석 산출물은 `reports/analysis/` 아래에 별도 MD/CSV로 저장한다.

## 기본 분석 기간

- 사용자가 기간을 지정하면 해당 기간을 사용한다.
- 기간이 없으면 최근 2주 운영 데이터를 기본으로 한다.
- 거래일 기준 시작일, 종료일, 포함된 trading_days를 최종 보고에 명시한다.

## 필수 엑셀 시트 목록

- Summary
- Daily Targets
- Scoring
- Candidate Eval
- Block Reasons
- Final Decisions
- Fills
- Fill Detail
- Daily Summary
- Compare
- Run Summary
- Snapshots
- Orders
- Warnings
- Recent Warnings
- Latest Targets
- Candidate Detail

## 시트별 컬럼 정의

### Summary

컬럼:
- metric
- value
- note

필수 metric:
- analysis_period
- generated_at
- daily_target_rows
- scoring_rows
- candidate_evaluations_rows
- trade_history_rows
- order_snapshot_rows
- fill_history_rows
- bot_log_rows
- daily_run_summary_rows
- entry_profit_snapshot_rows
- total_realized_profit_fill_history
- total_realized_profit_daily_summary
- top_profit_ticker
- top_profit_amount
- profit_without_top_ticker
- warning_count
- error_count

### Daily Targets

컬럼:
- trade_date
- target_count
- distinct_tickers
- avg_volume_ratio
- max_volume_ratio
- avg_price_change
- max_price_change
- first_created_at
- last_created_at

### Scoring

컬럼:
- trade_date
- score_count
- selected_count
- avg_total_score
- max_total_score
- min_total_score
- selected_avg_score
- selected_max_score

### Candidate Eval

컬럼:
- trading_date
- source
- eval_count
- buy_allowed_count
- order_submitted_count
- blocked_count
- avg_selection_score
- avg_final_score
- max_final_score
- first_evaluated_at
- last_evaluated_at

### Block Reasons

컬럼:
- trading_date
- source
- buy_block_reason
- count
- buy_allowed_count
- order_submitted_count
- avg_final_score
- max_final_score

### Final Decisions

컬럼:
- trading_date
- source
- final_decision
- count
- buy_allowed_count
- order_submitted_count

### Fills

컬럼:
- trade_date
- buy_count
- sell_count
- buy_amount
- sell_amount
- profit_usd
- avg_profit_rate
- win_count
- loss_count
- win_rate

### Fill Detail

컬럼:
- trade_date
- fill_time
- ticker
- ticker_name
- side
- quantity
- fill_price
- fill_amount
- profit_usd
- profit_rate
- order_no
- entry_reason
- strategy_version
- fill_notification_sent
- fill_notification_sent_at
- created_at

### Daily Summary

컬럼:
- trade_date
- mode
- strategy_version
- total_profit_usd
- total_profit_rate
- trade_count
- buy_count
- sell_count
- win_rate
- sample_sufficient
- created_at
- updated_at

### Compare

컬럼:
- trade_date
- fill_buy_count
- summary_buy_count
- buy_diff
- fill_sell_count
- summary_sell_count
- sell_diff
- fill_profit_usd
- summary_profit_usd
- profit_diff

### Run Summary

컬럼:
- trade_date
- mode
- realized_profit_usd
- realized_profit_rate
- eod_sell_count
- cancelled_order_count
- buy_fill_count
- sell_fill_count
- strategy_version
- updated_at

### Snapshots

컬럼:
- trade_date
- snapshot_count
- distinct_tickers
- negative_5m
- negative_10m
- negative_15m
- negative_20m
- negative_30m
- avg_final_profit_rate

### Orders

컬럼:
- trade_date
- order_count
- buy_orders
- sell_orders
- open_order_count
- unfilled_quantity
- first_created_at
- last_created_at

### Warnings

컬럼:
- log_level
- module
- message
- count
- first_created_at
- last_created_at

### Recent Warnings

컬럼:
- trade_date
- log_level
- module
- message
- created_at

### Latest Targets

컬럼:
- trade_date
- ticker
- ticker_name
- opening_volume
- average_volume_20d
- volume_ratio
- price_change
- created_at

### Candidate Detail

컬럼:
- trading_date
- source
- evaluation_time
- symbol
- symbol_name
- current_price
- selection_score
- soft_score_adjustment
- final_score
- buy_allowed
- order_submitted
- order_id
- buy_block_reason
- final_decision
- created_at

## Runner 분석 산출물

runner 분석 요청 시 아래 파일을 생성한다.

- `reports/analysis/runner_profile_summary.md`
- `reports/analysis/runner_ticker_comparison.csv`
- `reports/analysis/runner_lifecycle_<TICKER>.csv`
- `reports/analysis/runner_score_shadow.csv`
- `reports/analysis/noisy_universe_candidates.csv`
- `reports/analysis/missed_runner_candidates.csv`

### runner_profile_summary.md 필수 섹션

1. Data coverage
2. Profit concentration
3. Top winners
4. Top losers
5. Main runner lifecycle
6. Runner score proposal
7. Missed runner candidates
8. Noisy universe candidates
9. Protection, cooldown, and log impact
10. Recommendations
11. One-line conclusion

### runner_ticker_comparison.csv

컬럼:
- ticker
- group
- profit
- initial_score
- max_final
- allowed
- submitted
- volume_ratio
- price_change
- proxy_move
- key_reason

### runner_lifecycle_<TICKER>.csv

컬럼:
- time
- stage
- source
- score_status
- reason
- price
- quantity
- pnl
- note

### runner_score_shadow.csv

컬럼:
- ticker
- name
- runner_score
- profit
- group
- momentum_component
- volume_component
- score_component
- recheck_component
- overheat_component
- noise_penalty
- noise_flags
- notes

### noisy_universe_candidates.csv

컬럼:
- ticker
- name
- reason
- traded
- profit
- appeared_in

### missed_runner_candidates.csv

컬럼:
- ticker
- first_reason
- later_allowed
- allowed_no_order
- submitted
- estimated_move
- max_final
- note

주의:
- runner_score는 실제 매매 판단에 사용하지 않는 shadow/display-only 지표로 취급한다.
- intraday minute price table이 없으면 missed runner는 proxy 분석이라고 명시한다.
- `candidate_evaluations.current_price` 기반 추정은 실제 최고가/최저가가 아니다.

## Noisy universe 기준

아래는 noise flag 후보로 표시한다. 1차에서는 실제 제외하지 않고 display-only로 둔다.

- ETF
- ETN
- BOND
- LEVERAGED
- INVERSE
- WARRANT
- RIGHT
- UNIT
- TRUST
- FUND
- 2X
- 3X
- ULTRA
- SHORT
- suffix W / WS / WT / U
- extreme price_change

주의:
- MSTR처럼 단순히 R로 끝나는 정상 ticker를 suffix만으로 noise 처리하지 않는다.

## 해석 기준

- 후보는 충분한데 buy_allowed가 거의 없음
  - entry planner 조건이 너무 강할 수 있음
- buy_allowed는 있는데 order_submitted가 없음
  - limited_intraday / 주문보호 / 미체결 / cooldown 확인
- order_submitted는 있는데 fill이 없음
  - limit price / 미체결 / KIS order snapshot 확인
- fill은 있는데 daily_summary와 다름
  - summary 재생성 또는 report timing 확인
- top winner 제외 시 손익이 크게 마이너스
  - runner 의존도가 높음. 즉시 매수 조건 변경 금지, shadow 분석 우선
- noise 종목이 매매됨
  - universe filter 또는 display-only noise flag 우선

## 최종 보고 형식

1. PASS / WARN / FAIL 요약

2. 생성 파일
- Excel path
- CSV/MD path

3. 분석 기간
- start_date
- end_date
- trading_days

4. 데이터 범위
- table별 row count
- min/max date
- 누락 테이블

5. 핵심 결과
- 전체 손익
- top winner
- top loser
- top winner 제외 손익
- selected / buy_allowed / order_submitted / fill funnel

6. 주문이 안 나간 주요 원인
- 전역 진입 차단
- 후보 부족
- entry planner 차단
- order protection
- 미체결/retry
- cooldown/risk

7. runner 분석
- LASE-like winner가 있는지
- runner_score 상위
- 손실 종목과 차이
- missed runner 후보

8. noisy universe
- ETF/레버리지/인버스/워런트/유닛 후보
- 실제 매매된 noise 종목
- 제외 필터 제안 여부

9. 데이터 품질 WARN
- stale order lookup failure
- missing snapshot
- daily summary mismatch
- candidate_evaluations 누락

10. 다음 작업 추천
- 1순위
- 2순위
- 3순위
