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
