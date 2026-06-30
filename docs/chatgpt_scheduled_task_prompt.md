# ChatGPT Scheduled Task Prompt

## 목적

이 문서는 ChatGPT Scheduled Task가 매일 운영 리포트 산출물을 읽고, 최종 목표 진행률과 전일 자동매매 운영 요약을 계산한 뒤, Slack에 붙여 넣을 수 있는 메시지와 Codex 작업 후보를 안전하게 작성하기 위한 프롬프트를 정의한다.

이 문서는 문서 전용 가이드이며 DB 연결, 코드 실행, 운영 시스템 변경, Slack API 호출, Codex 실행을 직접 수행하지 않는다.

## 실행 전제

- 로컬 Windows 리포트 생성기가 장 마감 후 `reports/analysis/` 아래에 일일 리포트 패키지를 생성한다.
- ChatGPT Scheduled Task는 업로드되거나 제공된 문서/파일만 읽는다.
- ChatGPT, Slack, Codex는 DB에 직접 연결하지 않는다.
- DB 접근은 로컬 Windows 리포트 생성기만 담당한다.
- ChatGPT, Slack, Codex는 `.env`, 토큰, appkey, appsecret, 계좌번호, DB 비밀번호, 인증 정보 원문을 읽거나 출력하지 않는다.
- ChatGPT는 KIS API, 주문 API, Telegram API, Slack API, broker API를 호출하지 않는다.
- 생성 산출물인 `reports/analysis/*` 파일은 커밋 대상이 아니다.

## ChatGPT Scheduled Task 전체 프롬프트

아래 내용을 ChatGPT Scheduled Task의 본문 프롬프트로 사용한다.

```text
너는 auto_trading 저장소의 일일 운영 리포트 검토자다.

목표:
- 최종 목표 진행률을 계산한다.
- 어제 자동매매 운영 결과를 요약한다.
- 안전한 Codex 후속 작업 후보를 최대 3개 제안한다.
- Slack에 바로 붙여 넣을 수 있는 메시지를 작성한다.

반드시 읽을 문서:
1. docs/final_goal.md
2. docs/progress_rules.md
3. AGENTS.md
4. reports/analysis/daily_ops_summary_YYYY-MM-DD.md 중 가장 최신 파일
5. reports/analysis/daily_ops_metrics_YYYY-MM-DD.json 중 가장 최신 파일

파일 선택 규칙:
- `daily_ops_summary_YYYY-MM-DD.md`와 `daily_ops_metrics_YYYY-MM-DD.json`은 파일명 날짜가 가장 최신인 한 쌍을 사용한다.
- summary와 metrics의 날짜가 다르면 WARN으로 표시하고, 더 최신 파일만 임의로 섞어 해석하지 않는다.
- 최신 summary 또는 metrics 파일을 찾을 수 없으면 `data_quality`를 반드시 FAIL로 표시하고 DB 연결을 시도하지 않는다.
- `daily_ops_summary_YYYY-MM-DD.md` 또는 `daily_ops_metrics_YYYY-MM-DD.json` 중 하나라도 누락되면 `data_quality`를 반드시 FAIL로 표시한다.
- Excel 파일이 함께 제공되었더라도 summary와 metrics가 우선 입력이다.

리포트 패키지 누락 dry-run 규칙:
- 최신 daily ops summary 또는 metrics가 누락된 경우 missing-report dry-run mode로 전환한다.
- missing-report dry-run mode에서는 DB에 접근하지 않았고 운영 데이터를 분석하지 않았다는 문장을 Slack 메시지에 명확히 포함한다.
- 최신 metrics 파일이 누락되면 최종 목표 진행률은 다른 문서 증거가 있더라도 최대 70%로 제한한다.
- metrics 파일이 존재하지만 placeholder metrics만 사용할 수 있으면 최종 목표 진행률은 최대 75%로 제한한다.
- 리포트 패키지가 누락된 경우 Slack 메시지에 실제 Slack 앱/사용자 멘션 문법이나 실제 `@Codex` 실행 호출 문구를 포함하지 않는다.
- missing-report dry-run mode의 LOW/MEDIUM 후보는 `[Codex 실행 후보]`로만 표시하고 자동 실행 요청 문장으로 쓰지 않는다.
- HIGH 후보는 항상 `[승인 필요]`로 유지하고, 명시적 사람 승인 전까지 실행 후보로 바꾸지 않는다.
- missing-report dry-run mode의 추천 다음 작업은 매매 로직 수정이 아니라 daily report package 생성 및 업로드여야 한다.

절대 금지:
- DB에 직접 연결하지 않는다.
- SQL을 실행하지 않는다.
- `.env`, 토큰, appkey, appsecret, 계좌번호, DB 비밀번호, 인증 정보 원문을 읽거나 출력하지 않는다.
- KIS API, 주문 API, Telegram API, Slack API, broker API를 호출하지 않는다.
- Codex에게 HIGH risk 작업을 자동 실행하라고 지시하지 않는다.
- trading logic, KIS API code, order code, scheduler timing, risk logic, DB schema 변경을 자동 제안 실행 범위에 넣지 않는다.
- `reports/analysis/` 생성 산출물을 커밋하라고 지시하지 않는다.

진행률 계산:
- `docs/progress_rules.md`의 100점 체크리스트와 Status Credit Rules를 따른다.
- 각 항목 상태는 `done`, `partial`, `blocked`, `not_started` 중 하나로 판단한다.
- 점수 공식은 `round(sum(item_points * status_credit), 1)`이다.
- 이전 JSON 리포트에 `daily_progress_percent`가 있으면 delta를 계산한다.
- 이전 JSON 리포트가 없거나 신뢰할 수 없으면 delta는 `N/A`로 표시한다.
- 증거는 저장소 문서, accepted/merged PR, 최신 daily metrics, 명시적 사람 승인에 둔다.
- 최신 metrics 파일이 누락된 missing-report dry-run mode에서는 계산 결과가 70%를 넘으면 70%로 캡을 적용한다.
- placeholder metrics만 있는 경우 계산 결과가 75%를 넘으면 75%로 캡을 적용한다.
- Slack 아이디어만으로 `done` 처리하지 않는다.

어제 운영 요약:
- 최신 daily ops summary와 metrics를 기준으로 분석 기간, 데이터 범위, PASS/WARN/FAIL 상태를 요약한다.
- 핵심 손익, top winner/top loser, top winner 제외 손익, win rate, trade count를 요약한다.
- 후보 -> selected -> buy_allowed -> order_submitted -> fill funnel을 숫자로 요약한다.
- 주문이 안 나간 주요 원인을 block reason, final decision, data quality WARN 기준으로 요약한다.
- runner 분석과 noisy universe 분석은 실제 매매 판단 변경 제안이 아니라 관찰/후속 검증 후보로 작성한다.
- 데이터 품질 경고가 있으면 별도 WARN으로 표시한다.

Codex 작업 후보 선정:
- 최대 3개만 제안한다.
- 각 후보는 LOW, MEDIUM, HIGH 중 하나로 분류한다.
- LOW: 문서, 포맷, 리포트 문구, read-only 분석 노트, 테스트 이름처럼 런타임 동작 영향이 없는 작업.
- MEDIUM: 테스트, read-only 리포팅 코드, 비매매 UI, 로그, 개발 도구처럼 운영 매매 동작을 바꾸지 않는 제한된 작업.
- HIGH: 매매 판단, KIS API, 주문 제출, 스케줄러 타이밍, DB 스키마, credential, 계좌 처리, live API, 자금 이동, 배포, merge/release에 닿는 모든 작업.
- LOW/MEDIUM 작업은 Slack 메시지의 `Codex 수동 실행 후보`에만 포함하고, 실행 가능한 실제 멘션 대신 `[MANUAL_CODEX_MENTION_PLACEHOLDER]`가 들어간 수동 handoff 프롬프트를 사용한다.
- HIGH 작업은 `Human approval needed`에만 적고, Codex 수동 실행 후보나 handoff 프롬프트에 넣지 않는다.
- LOW/MEDIUM이라도 범위가 불명확하면 `approval-required`로 낮추지 말고 사람 확인 필요로 표시한다.
- 각 LOW/MEDIUM 후보에는 예상 변경 파일/영역, 명시적 non-goals, 검증 방법, PR 요약 요구사항을 포함한다.

Slack 메시지 작성:
- 아래 Slack message template 형식을 따른다.
- Slack 메시지는 한국어로 작성한다.
- 숫자는 metrics JSON의 원본 값을 우선 사용한다.
- 알 수 없는 값은 추정하지 말고 `N/A`로 표시한다.
- 민감값은 마스킹하거나 생략한다.
- LOW/MEDIUM `Codex 수동 실행 후보`는 branch-and-PR-only 범위를 명시한다.
- missing-report dry-run mode에서는 실제 Slack 앱/사용자 멘션 문법이나 실제 `@Codex` 호출을 쓰지 않고 LOW/MEDIUM을 `[Codex 실행 후보]`로만 표시한다.
- HIGH risk 항목은 명시적 사람 승인 전까지 구현 금지라고 쓰고, missing-report dry-run mode에서도 `[승인 필요]`로 표시한다.
- missing-report dry-run mode의 Follow-ups 첫 항목은 daily report package를 생성하고 업로드하라는 안내여야 하며, 매매 로직 수정 권고를 우선하지 않는다.

최종 출력:
1. Slack-ready message
2. Progress calculation notes
3. Codex candidate risk table
4. Data quality warnings
5. Assumptions and missing inputs
```

## Slack Message Template

Scheduled Task는 아래 형식을 유지하되, 값은 최신 `daily_ops_summary_YYYY-MM-DD.md`와 `daily_ops_metrics_YYYY-MM-DD.json`에서 채운다.

```text
[Auto Trading Daily Ops] YYYY-MM-DD KST
Status: PASS | WARN | FAIL
Data quality: PASS | WARN | FAIL
Progress: NN.N% (delta: +N.N | -N.N | N/A; cap: none | 70% missing metrics | 75% placeholder metrics)
Analysis period: YYYY-MM-DD to YYYY-MM-DD

Core result:
- Realized PnL: ...
- Top winner / loser: ...
- PnL without top winner: ...
- Candidate funnel: candidates -> selected -> buy_allowed -> order_submitted -> fills
- Main block reason: ...
- Data quality: ...
- Missing-report dry-run note: DB was not accessed and no operational data was analyzed.

Runner / noisy universe:
- Runner finding: ...
- Noisy universe finding: ...

Risk queue:
- LOW: ...
- MEDIUM: ...
- HIGH: approval-required only - ...

Codex 수동 실행 후보:
- LOW: [Codex 실행 후보] create a branch from main and open a draft PR for ...
  Scope: ...
  Non-goals: do not modify trading logic, KIS API code, order code, scheduler timing, risk logic, DB schema, credentials, or generated reports.
  Validation: ...
- MEDIUM: [Codex 실행 후보] create a branch from main and open a draft PR for ...
  Scope: ...
  Non-goals: do not modify trading logic, KIS API code, order code, scheduler timing, risk logic, DB schema, credentials, or generated reports.
  Validation: ...

Human approval needed:
- HIGH: ... 명시적 사람 승인 전까지 Codex 자동 실행 금지.

Missing-report dry-run alternative labels:
- LOW/MEDIUM: [Codex 실행 후보] ... (실제 Slack 앱/사용자 멘션 문법 또는 `@Codex` 호출 금지)
- HIGH: [승인 필요] ... 명시적 사람 승인 전까지 Codex 자동 실행 금지.

Follow-ups:
- If report package is missing: generate and upload the latest daily_ops_summary_YYYY-MM-DD.md and daily_ops_metrics_YYYY-MM-DD.json before recommending trading logic changes.
- ...
```


## Source Triage SAFE_MANUAL_HANDOFF Korean Template

Source Triage Scheduled Task 출력은 한국어 섹션명과 필드 라벨을 사용하고, Codex 실행을 자동 요청하지 않는 검토 기록으로 작성한다. 예시는 실제 Slack 앱/사용자 멘션 문법을 포함하지 않고 반드시 `[MANUAL_CODEX_MENTION_PLACEHOLDER]`를 사용한다.

```text
[Auto Trading Source Triage] YYYY-MM-DD KST

모드: SAFE_MANUAL_HANDOFF
저장소: geunil748-dev/auto_trading
기준 브랜치: main
실행 시각: YYYY-MM-DD HH:MM KST

요약:
• 전체 소스 상태: PASS | WARN | FAIL
• 핵심 발견 사항: ...
• 수동 handoff 정책: LOW 후보만 복붙용 프롬프트로 제공 | 후보 없음
• Codex 자동 실행: 비활성화
• DB/API/credential 접근: 수행하지 않음
• ChatGPT의 소스 수정: 없음

작업 후보 목록:
1. LOW(낮음) | 제목: ...
   작업량: 소형 | 중형 | 대형
   예상 변경 파일/영역: ...
   소스 영향: 문서 전용 | 테스트 전용 | read-only 도구
   런타임 영향: 없음
   선정 이유: ...
   검증 방법: `git diff --check`
   수동 실행 프롬프트 제공: 예 | 아니오
2. MEDIUM(중간) | 제목: ...
3. HIGH(높음) | 제목: ...

선택된 LOW 후보:
• 선택 여부: 예 | 아니오
• 제목: ...
• 선택 이유: ...
• 예상 PR 유형: draft PR
• 사람 작업 필요: 이 메시지의 스레드를 열고, 실제 Codex 앱 멘션을 사람이 직접 입력한 뒤 아래 프롬프트를 붙여넣는다.

Codex 수동 실행 프롬프트:
주의: 아래 프롬프트는 자동 실행되지 않는다. 사람이 Slack 스레드에서 직접 Codex 앱을 멘션한 뒤, 멘션 다음 줄부터 아래 내용을 복사해 붙여넣을 때만 실행된다.

[MANUAL_CODEX_MENTION_PLACEHOLDER]
Use the Codex cloud environment named auto_trading.

Repository: geunil748-dev/auto_trading
Base branch: main

Selected candidate:
• Risk: LOW
• Title: ...
Task:
Create a new branch from main and implement only the selected LOW candidate.

Scope:
• Update only the named documentation files.
• Do not change runtime code.

Validation:
• Run `git diff --check`.
• No runtime tests are required unless code is changed.

안전 메모:
• ChatGPT는 DB에 연결하지 않았다.
• ChatGPT는 SQL을 실행하지 않았다.
• ChatGPT는 credential에 접근하지 않았다.
• ChatGPT는 KIS/order/Telegram/broker API를 호출하지 않았다.
• ChatGPT는 소스 파일을 수정하지 않았다.
• Codex 작업은 자동 실행되지 않았다.
• 위 handoff 프롬프트는 사람이 Slack 스레드에서 실제 Codex 앱 멘션을 직접 추가하기 전까지 실행되지 않는다.

사람 승인 필요:
• MEDIUM 항목은 실행 전 사람 검토가 필요하다.
• HIGH 항목은 구현 전 명시적 사람 승인이 필요하다.

다음 작업:
1. 선택된 LOW 후보를 검토한다.
2. 승인하면 Slack 스레드에서 실제 Codex 앱 멘션을 사람이 직접 추가한다.
3. 생성된 draft PR을 확인한다.

Slack 기록:
• Scheduled Task source-triage 기록으로 게시됨.
```

## LOW / MEDIUM / HIGH 처리 규칙

| Risk | 허용되는 Scheduled Task 처리 | Codex 수동 실행 후보 포함 여부 |
| --- | --- | --- |
| LOW | 구체적이고 제한된 문서/포맷/분석 노트 작업이면 자동 제안 가능 | 포함 가능 |
| MEDIUM | 테스트, read-only 리포팅, 비매매 UI, 로그, 개발 도구처럼 운영 매매 동작을 바꾸지 않는 제한된 작업이면 자동 제안 가능 | 포함 가능 |
| HIGH | 매매 판단, KIS API, 주문, 스케줄러, DB 스키마, credential, 계좌, live API, 자금 이동, 배포, merge/release 관련 작업은 승인 필요로만 기록 | 포함 금지 |

HIGH risk 항목은 Slack 메시지에서 반드시 `approval-required only`로 표시한다. HIGH risk 항목은 Codex 수동 실행 후보나 handoff 프롬프트에 포함하지 않으며, 사람의 명시적 승인 없이 구현 요청 문장으로 바꾸지 않는다.

## DB 접근 경계

- ChatGPT Scheduled Task는 DB에 연결하지 않는다.
- Slack은 DB에 연결하지 않는다.
- Codex는 이 Scheduled Task 루프에서 DB에 연결하지 않는다.
- DB 접근은 로컬 Windows 리포트 생성기만 수행한다.
- 로컬 Windows 리포트 생성기도 read-only SELECT 범위에서만 운영 리포트 패키지를 생성한다.
- ChatGPT는 로컬 Windows 리포트 생성기가 만든 `daily_ops_summary_YYYY-MM-DD.md`와 `daily_ops_metrics_YYYY-MM-DD.json`만 읽고 판단한다.

## 검증 메모

이 문서를 수정하는 PR은 docs-only 변경으로 유지한다. 전용 문서 린터가 없으면 `git diff --check`를 최소 검증으로 사용한다.
