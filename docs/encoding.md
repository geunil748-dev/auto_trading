# Encoding Guide

이 저장소의 텍스트 파일은 Windows 11, PowerShell, Python, MSSQL 환경에서 모두 UTF-8 without BOM을 기준으로 관리한다.

## 기본 원칙

- 소스와 문서는 UTF-8 without BOM으로 저장한다.
- 한글 로그, 한글 UI 문구, 한글 문서는 CP949/EUC-KR/ANSI로 저장하지 않는다.
- PowerShell에서 파일을 쓸 때는 Windows PowerShell 5.1의 `-Encoding utf8`이 BOM을 만들 수 있음을 주의한다.
- Python에서 한글이 들어갈 수 있는 파일을 읽고 쓸 때는 `encoding="utf-8"`을 명시한다.
- JSON에 사용자 표시 문구가 들어가면 `ensure_ascii=False`를 사용한다.

## PowerShell

스크립트 시작부에서 콘솔 출력 인코딩을 UTF-8로 고정한다.

```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
```

UTF-8 without BOM으로 파일을 써야 할 때는 `Set-Content -Encoding utf8` 대신 .NET API를 사용한다.

```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $text, $utf8NoBom)
```

## Python

파일 입출력은 인코딩을 명시한다.

```python
path.write_text(text, encoding="utf-8")
payload = json.loads(path.read_text(encoding="utf-8"))
```

JSON 파일에는 한글을 그대로 보존한다.

```python
json.dumps(payload, ensure_ascii=False, indent=2)
```

## MSSQL

한글 사용자 표시 문자열을 저장하는 컬럼은 `NVARCHAR`를 사용한다. 티커, 상태 코드, 해시, 전략 버전처럼 ASCII 코드 성격의 값은 `VARCHAR`를 사용할 수 있다.

## 점검 명령

```powershell
$env:PYTHONPATH="C:\auto_trading\src"
C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_text_encoding.py
C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check --no-cache src tests
git diff --check
```
