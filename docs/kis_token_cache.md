# KIS Token Cache

실서버와 테스트서버가 같은 한국투자증권 모의투자 앱 키를 사용할 때는 DB 토큰 캐시를 사용한다. 각 서버가 시작이나 잔고조회 때마다 토큰을 새로 발급하지 않고, MSSQL에 저장된 유효 토큰을 공유한다.

## DB 테이블

`init-db`는 `dbo.KisTokenCache` 테이블을 생성한다. 테이블이 이미 있으면 재생성하지 않는다.

주요 컬럼:

- `environment`: `test` 또는 `real`
- `app_key_hash`: 앱 키 원문 대신 `base_url + app_key` 해시
- `access_token`: KIS access token
- `token_type`: 기본 `Bearer`
- `expires_at`: 토큰 만료 시각
- `issued_at`, `last_used_at`, `created_at`, `updated_at`: 운영 확인용 시각

`environment + app_key_hash` 조합은 unique로 유지한다.

## 동작 방식

1. 메모리 캐시에 유효 토큰이 있으면 재사용한다.
2. `KIS_TOKEN_STORE=db`이면 DB에서 유효 토큰을 먼저 조회한다.
3. 만료까지 `KIS_TOKEN_REFRESH_MARGIN_SECONDS`보다 많이 남아 있으면 DB 토큰을 재사용하고 `last_used_at`을 갱신한다.
4. 유효 토큰이 없고 `KIS_ALLOW_TOKEN_REFRESH=false`이면 새 토큰을 발급하지 않고 명확한 오류를 낸다.
5. 갱신이 허용된 서버만 `sp_getapplock`으로 `kis_token_refresh:{environment}:{app_key_hash}` 락을 잡는다.
6. 락을 잡은 뒤 DB를 다시 조회하고, 그래도 유효 토큰이 없을 때만 KIS 토큰 발급 API를 호출한다.
7. 발급 성공 시 DB에 upsert한다.

## .env 예시

실서버 또는 대표 발급 서버:

```env
KIS_TOKEN_STORE=db
KIS_TOKEN_REFRESH_MARGIN_SECONDS=300
KIS_ALLOW_TOKEN_REFRESH=true
```

테스트서버:

```env
KIS_TOKEN_STORE=db
KIS_TOKEN_REFRESH_MARGIN_SECONDS=300
KIS_ALLOW_TOKEN_REFRESH=false
```

테스트서버는 유효 DB 토큰이 없거나 만료되면 새 발급을 하지 않는다. 먼저 실서버나 대표 발급 서버에서 토큰을 갱신한 뒤 테스트서버를 실행한다.

## 운영 원칙

- `access_token`은 로그에 출력하지 않는다.
- KIS 앱 키 원문은 DB에 저장하지 않는다.
- `.env`, `.kis-token-*.json`, 로그 파일은 커밋하지 않는다.
- 같은 모의투자 앱 키를 쓰는 서버는 같은 MSSQL DB를 보게 한다.
- 토큰 만료 전 대표 서버 1개만 갱신하도록 테스트서버는 `KIS_ALLOW_TOKEN_REFRESH=false`를 권장한다.

## 확인 명령

```powershell
$env:PYTHONPATH="C:\auto_trading\src"
python -m trading_bot init-db
python -m trading_bot kis-account
```
