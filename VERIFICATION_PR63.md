# PR #63 Post-Merge Verification

## Summary

- **Verified HEAD:** `9294baa2a88bed0a647e95e97829b27ff419e19f`
- **Verification time:** `2026-07-11T22:00:31+09:00` (KST)
- **Repository / target:** `geunil748-dev/auto_trading`, `origin/main`
- **Related PR:** `#63`
- **Base / merge parents:** first parent `78d17ae4fae6a6138d372d966359b64f0193a9c1`, PR head parent `cc2598f97f780f239e52b746a95a6e5bd48740fe`
- **Final decision:** `READY_FOR_MOCK_OBSERVATION`

검증은 별도 detached worktree에서 수행했다. 주문 API, 시세 API, Telegram API, KIS client, 외부 DB, 실제 `.env`를 사용하지 않았고 실투자 활성화·잠금 해제·비상정지·전략 수치는 변경하지 않았다.

## Worktree state

- `git fetch origin main --prune` 후 `origin/main`과 검증 worktree의 HEAD가 모두 대상 merge SHA와 일치했다.
- 보고서 작성 전 `git status --short` 결과는 비어 있었다.
- 검증 중 코드나 설정 파일은 수정하지 않았다. 보고서 작성 후의 유일한 새 파일은 `VERIFICATION_PR63.md`이다.
- `git diff --check`는 exit code 0, 출력 없음으로 통과했다.

## Changed file scope

명령:

```text
git diff --name-status 78d17ae4fae6a6138d372d966359b64f0193a9c1..9294baa2a88bed0a647e95e97829b27ff419e19f
```

결과는 19개 파일이다.

```text
M  .env.example
M  README.md
M  src/trading_bot/apscheduler_runner.py
M  src/trading_bot/cli.py
M  src/trading_bot/config.py
M  src/trading_bot/entry_planner.py
A  src/trading_bot/intraday_data_quality.py
M  src/trading_bot/models.py
M  src/trading_bot/sql_monitor_formatters.py
M  src/trading_bot/strategy_metadata.py
M  src/trading_bot/trading_event_logger.py
A  tests/test_apscheduler_runner.py
A  tests/test_cli_settings_propagation.py
M  tests/test_config.py
M  tests/test_core_rules.py
A  tests/test_fixed_recheck_missing_data.py
A  tests/test_intraday_condition_states.py
A  tests/test_intraday_missing_data.py
A  tests/test_strategy_metadata.py
```

## Requirement-by-requirement result

| 상태 | 요구사항 | 소스 및 테스트 근거 |
|---|---|---|
| PASS | `IntradayConditionState`가 `PASS` / `FAIL` / `NO_DATA`를 구분 | `src/trading_bot/models.py:15-18` |
| PASS | `minutes_above_breakout=None`과 실제 `0.0`을 구분 | nullable 모델은 `models.py:136`; `intraday_data_quality.py:49-52,192-195`에서 `None`만 `NO_DATA`, `0.0`은 실제 임계값 비교. 회귀 테스트 `tests/test_intraday_missing_data.py:202-219` |
| PASS | `APP_MODE=test`, `MOCK_TRADING=true`, `AUTO`를 `LOG_ONLY`로 해석 | 설정 전달 `config.py:256-265`; resolver `config.py:1036-1053`; 조합 테스트 `tests/test_config.py:79-105` |
| PASS | `APP_MODE=real`은 명시적 `LOG_ONLY` 요청도 `BLOCK`으로 강제 | `config.py:1047-1050`; 테스트 조합 `tests/test_config.py:85-86,89-105` |
| PASS | test이지만 `MOCK_TRADING=false`이면 `BLOCK` | `config.py:1047-1050`; 테스트 조합 `tests/test_config.py:81,83,89-105` |
| PASS | `NO_DATA` reason과 실제 `*_FAILED` reason을 분리 | missing reason은 `intraday_data_quality.py:86-93`; 실제 FAIL 적용은 `entry_planner.py:317-349`; missing 정책 적용은 `entry_planner.py:354-358`; 표시 코드도 `entry_planner.py:244-257`에서 분리 |
| PASS | 필수 데이터가 여러 개 누락되면 `REQUIRED_INTRADAY_DATA_MISSING` 사용 | `intraday_data_quality.py:184-185`, `entry_planner.py:354-356`, `trading_event_logger.py:684-687`; 테스트 `tests/test_intraday_missing_data.py:140-152` |
| PASS | CandidateEvaluation JSON에 필수 데이터 품질 context를 모두 기록 | `condition_states`, 두 quality status, missing/available fields, policy, app mode, mock 여부가 `intraday_data_quality.py:144-163`에 있고, `entry_planner.py:496-501,586-596`에서 `condition_result_json`으로 직렬화 |
| PASS | 후보평가당 TradingEvent 1건이며 details에 누락 reason을 보존 | 각 planner 종료 경로가 `_safe_save_candidate_evaluation`을 한 번 호출하고, 정상 저장 경로는 event recorder를 한 번 호출한다(`entry_planner.py:71-197,671-680`). details 보존과 단일 event 기록은 `trading_event_logger.py:94-147`. A/B count 스모크에서도 각각 정확히 1건 |
| PASS | 후보평가당 `candidate_evaluation` BotLog 요약 1건 | 정상 저장 경로의 summary는 `entry_planner.py:692-706`에 한 건. 추가 VWAP 로그는 별도 module `entry_planner`(`707-717`). 테스트 `tests/test_intraday_missing_data.py:100-102` 및 A/B count 스모크에서 각각 정확히 1건 |
| PASS | 실제 데이터가 있고 기준 미달이면 기존 `*_FAILED` 동작 유지 | `_optional_state`와 기존 실패 적용 경로 `intraday_data_quality.py:192-195`, `entry_planner.py:317-349`. low volume, zero-minute hold, pullback false, VWAP truth table 테스트는 `tests/test_intraday_missing_data.py:156-179,202-219,242-252`, `tests/test_intraday_condition_states.py:58-90` |
| PASS | 비활성 조건이 required quality를 오염시키지 않음 | `tests/test_intraday_condition_states.py:93-104`에서 raw completeness는 `INCOMPLETE`여도 disabled VWAP 조건의 `required_data_quality_status`는 `COMPLETE` |
| PASS | 잘못된 설정은 scheduler heartbeat/job 등록보다 먼저 실패 | `src/trading_bot/apscheduler_runner.py:15-40`; `tests/test_apscheduler_runner.py:8-30`에서 KIS 설정 로드 및 heartbeat 파일 생성이 모두 발생하지 않음을 검증 |
| PASS | risk, exit, order payload, DB schema/migration, 실투자 잠금장치 미변경 | 아래 `Out-of-scope files unchanged evidence`의 base/head blob 및 diff 범위 확인 |

`FAIL` 또는 `NOT VERIFIED`로 분류된 정적 요구사항은 없다.

## Focused test command and result

실행 명령:

```text
python -m pytest tests/test_intraday_missing_data.py tests/test_intraday_condition_states.py tests/test_fixed_recheck_missing_data.py tests/test_config.py tests/test_apscheduler_runner.py tests/test_cli_settings_propagation.py tests/test_strategy_metadata.py -q
```

정확한 결과:

```text
67 passed in 2.82s
```

요청된 mock/real 정책, feature별 null reason, `None` 대 `0.0`, 값 존재 시 PASS/FAIL, 빈 intent executor의 submit 0건, 비활성 조건 quality 상태, scheduler 선행 실패 시나리오를 포함하며 모두 통과했다.

## Full pytest exact result

명령:

```text
python -m pytest
```

정확한 결과:

```text
collected 632 items
632 passed in 148.46s (0:02:28)
```

## Compile result

명령:

```text
python -m compileall src tools tests
```

결과: exit code 0. `src`, `tools`, `tests` 컴파일 오류 없음.

## JavaScript syntax result

시스템 PATH에는 `node`가 등록되어 있지 않아 bare `node` 명령은 실행되지 않았다. 이를 성공으로 간주하지 않고, 설치된 번들 Node를 절대 경로로 지정해 다시 검사했다.

- Node: `v24.14.0`
- `monitor/app.js`: PASS
- `monitor/js/**/*.js`: 9개 PASS
- 총 검사 파일: 10개
- 최종 exit code: 0

## Mock LOG_ONLY evidence

네트워크 없는 결정론적 스모크 A는 직접 만든 `TradingSettings`/`BreakoutInput`, `InMemoryDailyRepository`, fake submitter만 사용했다. 모든 선택적 장중 feature를 `None`으로 두었다.

- 요청/적용 정책: `LOG_ONLY` / `LOG_ONLY`
- BuyIntent: 1건 (`SMOKE`)
- `buy_allowed=true`, `order_submitted=false`
- event: `BUY_ALLOWED`, `is_blocking=false`
- missing reasons:
  - `BREAKOUT_CLOSE_DATA_MISSING`
  - `BREAKOUT_HOLD_DATA_MISSING`
  - `VOLUME_INCREASE_DATA_MISSING`
  - `VWAP_MA20_DATA_MISSING`
  - `PULLBACK_REBREAK_DATA_MISSING`
- fake submitter 호출: 0건

## Real BLOCK evidence

동일 입력으로 real/non-mock에 `LOG_ONLY`를 요청한 결정론적 스모크 B 결과다.

- 요청/적용 정책: `LOG_ONLY` / `BLOCK`
- BuyIntent: 0건
- `buy_allowed=false`
- `buy_block_reason=REQUIRED_INTRADAY_DATA_MISSING`
- event: `BUY_BLOCKED`, `is_blocking=true`
- 빈 intents를 executor에 전달한 결과 거래: 0건
- fake submitter 호출: 0건

두 스모크 모두 실제 KIS client, 외부 DB, API, `.env`를 생성·조회하지 않았으며 assertion과 프로세스 exit code 0을 확인했다.

## Log/event cardinality evidence

| 스모크 | CandidateEvaluation | TradingEvent | module=`candidate_evaluation` BotLog |
|---|---:|---:|---:|
| A: mock / all optional features `None` | 1 | 1 | 1 |
| B: real / requested `LOG_ONLY` | 1 | 1 | 1 |

각 count는 정확히 `1 / 1 / 1`인지 assertion했다. 구현상 단일 저장 호출과 fallback 비활성화 근거는 `entry_planner.py:671-706`, 이벤트 details 근거는 `trading_event_logger.py:94-147`이다.

## Out-of-scope files unchanged evidence

base `78d17ae4...`와 merge HEAD `9294baa2...`의 blob을 직접 비교했고 다음 경로가 동일했다.

| 범위 | 동일 파일 근거 |
|---|---|
| Risk / exit | `risk.py` `07b68a6573f2a184665c2afb20c103405cfd5010`; `exit_planner.py` `217ebe66c88fa2b0ac84772c88d159afaec83556` |
| 주문 payload / 실행 | `adapters/kis_overseas.py` `97ca6cba...`; `adapters/kis_orders.py` `16f381d0...`; `adapters/kis_http.py` `522519d6...`; `composition.py` `a4a87c0d...`; `order_execution.py` `64ca15f2...`; `scheduler_orders.py` `a771a5f8...` |
| DB schema / persistence | `db/schema.sql` `f208b1d0...`; `database.py` `f8141653...`; `repositories.py` `4826e898...`; `runtime_settings_store.py` `562a583c...` |
| 실투자 잠금 / control | `real_trading_guard.py` `d8db9ddc...`; `real_trading_control.py` `bb019c4b...`; `monitor_server.py` `722ec8d9...`; `dashboard_state.py` `036a95f8...` |

위 경로는 19개 변경 파일 목록에도 포함되지 않는다. `config.py`의 변경은 누락 데이터 정책을 real에서 `BLOCK`으로 강제하며, 기존 실투자 enable/emergency-stop gate를 완화하지 않는다.

## CI run SHA/ref and result

GitHub Actions 메타데이터와 로그를 읽기 전용으로 확인했다. workflow 재실행은 필요하지 않았고 수행하지 않았다.

| 구분 | run | SHA / ref / event | 결과 | 로그에서 확인한 pytest | compileall / JavaScript syntax |
|---|---|---|---|---|---|
| PR #63 CI | [29152241320](https://github.com/geunil748-dev/auto_trading/actions/runs/29152241320) | `cc2598f97f780f239e52b746a95a6e5bd48740fe` / `codex/preopen-fix-intraday-nodata` / `pull_request` | `completed / success` | `632 passed in 144.51s` | PASS / PASS |
| main merge push CI | [29152458213](https://github.com/geunil748-dev/auto_trading/actions/runs/29152458213) | `9294baa2a88bed0a647e95e97829b27ff419e19f` / `main` / `push` | `completed / success` | `632 passed in 144.94s` | PASS / PASS |

두 run 모두 `python -m pytest`, `python -m compileall src tools tests`, `node --check monitor/app.js` 및 `monitor/js` 재귀 검사가 성공했다. PR run의 metadata `headSha`는 PR branch head `cc2598f...`이며 merge-ref 전용 실행으로 표시되지 않는다. 별도로 정확한 merge commit `9294baa...`에 대한 `main` push CI가 있으므로 병합 후 상태도 CI로 검증됐다.

PR 본문 수치와 로그 실측값은 구분했다. PR 본문의 `124 passed`는 별도 집중 테스트 서술이며 Actions 로그에서 그 실행을 확인한 값이 아니다. PR 본문의 full pytest `632 passed in 140.55s`도 본문 기재값이고, Actions 로그 실측 시간은 위 표의 `144.51s` 및 `144.94s`다. 현재 HEAD의 로컬 독립 실측은 `632 passed in 148.46s`다.

## Remaining risks

- 이 PR은 실제 KIS 분봉 API를 새로 연동하지 않는 범위다. 실제 장중 feature 공급이 계속 비어 있으면 mock에서는 `LOG_ONLY` 표본이 쌓이고 real에서는 의도대로 fail-closed 차단된다.
- 검증은 의도적으로 외부 DB와 실거래·시세·알림 API를 사용하지 않았다. 따라서 운영 DB 쓰기, 실제 시장 입력, 브로커 응답에 대한 end-to-end 검증은 이번 결과의 범위 밖이다.
- 운영 관찰 단계에서는 feature별 missing 비율, `required_data_quality_status`, `BUY_ALLOWED`/`BUY_BLOCKED`, 후보평가·이벤트·BotLog의 1:1:1 cardinality를 다음 주 표본으로 재확인해야 한다.
- 이 보고서는 검증 산출물이며 코드 변경·커밋·새 PR은 만들지 않았다.

## Final decision

`READY_FOR_MOCK_OBSERVATION`

요구된 정적 범위, 집중 테스트, 전체 회귀, compileall, diff/JavaScript 검사, 네트워크 없는 A/B 스모크, PR 및 main merge CI가 모두 통과했다. 실패를 재현한 항목은 없으며 자동 수정이 필요한 코드도 없다.
