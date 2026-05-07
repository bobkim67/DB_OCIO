# scripts/ — Desktop Launcher

DB OCIO Dashboard 더블클릭 launcher.
FastAPI(8000) + React Vite(5173) 두 서버를 한 번에 띄우고 브라우저를 자동으로 연다.

## 파일

| 파일 | 역할 |
|---|---|
| `launch_dashboard.bat` | 메인 launcher. 바탕화면 `DB OCIO Dashboard.lnk` 의 target. FastAPI/Vite 자식 .bat 을 각각 별도 창에서 띄우고 5초 뒤 브라우저 open. |
| `launch_fastapi.bat` | `api\.venv` 의 uvicorn 으로 `api.main:app` 을 `127.0.0.1:8000 --reload` 실행. |
| `launch_vite.bat` | `C:\Program Files\nodejs` 를 PATH 앞에 붙이고 `web\node_modules\.bin\vite.cmd` 을 `127.0.0.1:5173` 실행. |
| `install_desktop_shortcut.bat` | 바탕화면에 `DB OCIO Dashboard.lnk` 1회 설치 (재설치 / 다른 PC 셋업 용). 내부적으로 `_install_shortcut.ps1` 호출. |
| `_install_shortcut.ps1` | shortcut 생성 로직 (PowerShell `WScript.Shell.CreateShortcut`). 아이콘 = `shell32.dll,13` (모니터). |

## 사용

### 첫 1회 셋업 (다른 PC 또는 .lnk 삭제 시)
```
scripts\install_desktop_shortcut.bat   ← 더블클릭
```
바탕화면에 `DB OCIO Dashboard` 아이콘 생성.

### 평상시
바탕화면 `DB OCIO Dashboard` 더블클릭.
- launcher 창 (3초 뒤 자동 종료)
- FastAPI 창 (port 8000)
- Vite 창 (port 5173)
- 브라우저 (`http://127.0.0.1:5173`)

각 서버 종료는 해당 cmd 창에서 `Ctrl+C`.

## 설계 원칙

- **ASCII 전용**: 한국어 Windows cmd.exe (CP949) ↔ UTF-8 .bat 인코딩 충돌 방지. 모든 명령행은 ASCII, 한국어는 README 에서만.
- **child .bat 분리**: 외부 cmd 의 `%PATH%` 확장 + 중첩 따옴표가 `cmd /k "..."` 안에서 깨지는 문제를 회피. 각 자식 .bat 은 자체 cwd / PATH 설정.
- **첫 시작 5초 대기**: FastAPI 부팅(DB 핸드셰이크 포함) 시간 확보 후 브라우저 open. 부족하면 페이지 새로고침.
- **에러 시 창 유지**: 자식 .bat 끝에 `pause`. 어느 서버가 실패했는지 진단 가능.

## 의존

- `api\.venv` (Python 3.14 + fastapi/uvicorn/...)
- `web\node_modules` (`npm install` 1회 후)
- `C:\Program Files\nodejs` (Node.js 설치 경로 — 변경 시 `launch_vite.bat` 의 `set "PATH=..."` 수정)
- ports 8000, 5173 비점유

## 종료 정책

- launcher 창은 자동 종료. FastAPI / Vite 창은 사용자 명시적 종료 (`Ctrl+C` 또는 X).
- 좀비 socket 발생 시: `netstat -ano | findstr ":8000"` / `:5173"` → `taskkill /F /PID <PID>`.
