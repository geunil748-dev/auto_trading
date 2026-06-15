## 운영 데이터 엑셀 분석 규칙

사용자가 "2주 데이터 엑셀로 정리해줘", "운영 데이터 리뷰해줘", "runner 분석해줘"라고 요청하면 [docs/data_review_excel_spec.md](docs/data_review_excel_spec.md)의 형식을 따른다.

기본 원칙:
- read-only SELECT만 수행한다.
- 코드 수정, 커밋, PR 생성은 하지 않는다.
- DB INSERT / UPDATE / DELETE / ALTER 금지.
- KIS API, 주문 API, Telegram API 호출 금지.
- scheduler / monitor 재시작 금지.
- `.env`, 토큰, appkey, appsecret, 계좌번호 원문 출력 금지.
- 계좌번호나 민감값은 마스킹한다.
- 분석 산출물은 `reports/analysis/`에 저장하되 커밋하지 않는다.

기본 산출물:
- `auto_trading_review_YYYY-MM-DD.xlsx`
- runner 분석 요청 시 `reports/analysis/runner_profile_summary.md`
- runner 분석 요청 시 관련 CSV 파일들

분석 후 최종 보고에는 반드시 아래를 포함한다:
1. PASS / WARN / FAIL 요약
2. 분석 기간
3. 데이터 범위
4. 핵심 손익
5. 후보 -> selected -> buy_allowed -> order_submitted -> fill funnel
6. 주문이 안 나간 주요 원인
7. runner 분석
8. noisy universe 분석
9. 데이터 품질 WARN
10. 다음 작업 추천

주의:
- AGENTS.md에 상세 컬럼 정의를 전부 넣지 말 것.
- 상세 내용은 `docs/data_review_excel_spec.md`로 분리한다.

## 브랜치 병합 누락 방지 규칙

브랜치 병합을 요청받으면 단순히 `git merge` 결과만 믿지 말고, 병합 대상 브랜치와 현재 `main`의 실제 소스 차이를 먼저 확인한다.

병합 전 필수 확인:
- 현재 브랜치, 작업트리 상태, 원격 대비 ahead/behind 상태를 먼저 확인한다.
- 병합할 브랜치의 최신 커밋 목록과 변경 파일 목록을 확인한다.
- `git diff --name-status main...<branch>` 또는 merge-base 기준 diff로 브랜치 고유 변경 범위를 확인한다.
- 같은 브랜치가 과거에 merge 후 revert된 이력이 있는지 확인한다.
- 과거 merge/revert가 있으면 `git diff <merge_commit>^1 <merge_commit>`와 현재 `main`을 비교해 실제로 살아 있는 기능과 빠진 기능을 분리한다.

병합 중 원칙:
- 전체 브랜치 병합이 위험하거나 사용자가 일부 기능만 원하면 cherry-pick/수동 반영 범위를 명확히 적는다.
- 충돌 해결 시 `ours`/`theirs`로 덮어쓰기 전에 빠지는 파일, 함수, DB 컬럼, 테스트를 목록화한다.
- 특히 텔레그램 알림, DB 컬럼 마이그레이션, 스케줄러, 주문/체결 중복 방지 로직은 누락 여부를 별도로 확인한다.
- 기존 정상 동작 코드를 되돌리는 대규모 revert는 사용자에게 영향 범위를 설명한 뒤 진행한다.

병합 후 필수 확인:
- 병합 브랜치의 주요 기능 단위별로 현재 `main`에 실제 코드가 남아 있는지 `rg`와 `git diff main <branch>`로 확인한다.
- 새 DB 컬럼이 포함된 기능은 `db/schema.sql`, repository ensure-schema, port/interface, 테스트가 함께 반영됐는지 확인한다.
- 알림 기능은 발송 함수뿐 아니라 중복 방지 상태 저장/마킹 로직까지 확인한다.
- UI 기능은 HTML, JS, CSS, formatter/label, API payload, 테스트가 함께 반영됐는지 확인한다.
- 관련 테스트를 실행하고, 실행하지 못한 테스트는 이유를 결과 보고에 명시한다.
- 최종 보고에는 병합된 기능, 의도적으로 제외한 기능, 아직 남은 누락 후보, 테스트 결과를 반드시 포함한다.
