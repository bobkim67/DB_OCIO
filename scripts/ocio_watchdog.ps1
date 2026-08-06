# =====================================================================
# OCIO 대시보드 감시견(watchdog) — 포트 8020 이 죽으면 즉시 재기동
#
# - 15초 주기로 8020 LISTEN 확인. 죽어 있으면 5초 후 재확인(이중확인) 뒤
#   uvicorn 을 숨김창으로 재기동 (api\.venv, launch_dashboard.bat 과 동일 커맨드).
# - launch_dashboard.bat 이 빌드/재시작 중일 때는 .cache\launcher_active.flag
#   가 있으면(15분 이내) 재기동을 건너뜀 — 런처와 포트 충돌 방지.
# - 기록: logs\watchdog.log (감시견 이벤트), logs\server.log (uvicorn 파일 로그).
# - 종료 흔적: logs\watchdog.heartbeat 를 15초마다 갱신. 정상 종료·중지 스크립트는
#   이 파일을 지우므로, 남아 있으면 강제 종료/로그오프/크래시다. 파일의 갱신 시각이
#   곧 사망 시각이고, 다음 기동 때 그 사실이 watchdog.log 에 한 줄로 남는다.
#   heartbeat 에는 자원 지표(ws/pm/handles/threads/uptime)와 **최근 60초 신규 프로세스**
#   (new60s)를 같이 적는다 — 수치가 평소와 같으면 외부 kill(3회 확인), 우상향이면 누수.
#   new60s 는 다음 사망 때 "그 순간 무엇이 돌았는지" 를 남겨 범인 후보를 좁힌다.
# - 종료 코드: `ocio_watchdog_run.cmd` 로 띄우면 죽은 뒤 rc 가 watchdog.log 에 남는다.
#   (taskkill=1 / Ctrl+C=-1073741510 / 그 외=죽인 프로그램 고유값)
# - 단일 인스턴스: 이미 실행 중이면 즉시 종료.
#
# 수동 실행:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ocio_watchdog.ps1
# 자동 시작:  scripts\install_watchdog_autostart.bat (시작프로그램 등록 + 즉시 기동)
# =====================================================================
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
$Port = 8020
$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Log = Join-Path $LogDir "watchdog.log"
$Beat = Join-Path $LogDir "watchdog.heartbeat"
$Flag = Join-Path $Root ".cache\launcher_active.flag"

function WLog([string]$msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $msg" | Add-Content -Path $Log -Encoding UTF8
}

# ---- 단일 인스턴스 (세션 내 mutex) ----
$created = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\OCIO_Dashboard_Watchdog", [ref]$created)
if (-not $created) { exit 0 }

function PortUp {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function LauncherActive {
    # 런처가 빌드/재시작 중 (플래그 15분 이내) → 감시견은 손대지 않음
    if (-not (Test-Path $Flag)) { return $false }
    $age = (Get-Date) - (Get-Item $Flag).LastWriteTime
    if ($age.TotalMinutes -gt 15) { Remove-Item $Flag -Force; return $false }
    return $true
}

# ---- 직전 인스턴스가 어떻게 끝났는지 기록 ----
# 정상 종료(아래 Exiting 핸들러)·중지 스크립트는 heartbeat 를 지운다.
# 그래도 남아 있으면 강제 종료/로그오프/크래시 — 마지막 생존 시각을 로그에 남긴다.
if (Test-Path $Beat) {
    $lastBeat = (Get-Item $Beat).LastWriteTime
    $prevInfo = (Get-Content $Beat -TotalCount 1)
    $gapMin = [int]((Get-Date) - $lastBeat).TotalMinutes
    WLog "previous instance ended WITHOUT shutdown record - last alive $($lastBeat.ToString('yyyy-MM-dd HH:mm:ss')) ($gapMin min ago, $prevInfo) - taskkill/logoff/crash?"
    Remove-Item $Beat -Force
}

# ---- 사망 원인 계측 (2026-08-06) ----
# 2026-07-29 00:23 · 2026-08-04 00:58 두 번 다 자정 직후에 프로세스만 사라졌다.
# 크래시(WER 무기록)·로그오프(다른 프로세스 생존)·정상종료(위 핸들러 무기록)가 전부
# 배제돼 외부 kill 이 유력하나, 프로세스 종료 감사(4689)는 관리자 권한이 필요해 못 켠다.
# → heartbeat 에 자원 지표를 같이 남겨 다음 사망 때 "자원 누수로 자살"과 "외부 kill"을
#   가른다. 마지막 heartbeat 의 수치가 평소와 같으면 외부 kill 이다.
$proc = Get-Process -Id $PID

# 사망 직전 **주변 스냅샷** (2026-08-07) — 3회차까지 자원은 정상이었고 시각은 전부
# 00~01시대였다. 즉 야간에 도는 무언가가 죽인다는 뜻인데, 지금은 그 순간 무엇이
# 돌았는지가 백지다. heartbeat 에 **최근 60초 내 새로 뜬 프로세스**를 같이 적어
# 다음 사망 때 범인 후보를 좁힌다. (프로세스 종료 감사·Sysmon 은 관리자 권한 필요)
function NewNeighbors {
    $cut = (Get-Date).AddSeconds(-60)
    $names = @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -ne $PID -and $_.StartTime -and $_.StartTime -gt $cut } |
        Select-Object -ExpandProperty ProcessName -Unique)
    if (-not $names) { return '-' }
    if ($names.Count -gt 6) { $names = $names[0..5] + '…' }
    return ($names -join ',')
}

# ---- 정상 종료 흔적 (Ctrl+C·창닫기·exit. 강제 종료는 못 잡음 → heartbeat 담당) ----
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action ([scriptblock]::Create(@"
    "`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | watchdog stopping (pid `$PID) - graceful exit" | Add-Content -Path '$Log' -Encoding UTF8
    Remove-Item '$Beat' -Force -ErrorAction SilentlyContinue
"@)) | Out-Null

WLog "watchdog started (pid $PID, port $Port, interval 15s)"

while ($true) {
    # 생존 신호 (15s 주기). 이 한 줄이 다음 기동 때 사망 기록에 그대로 실린다.
    $proc.Refresh()
    $up = [int]((Get-Date) - $proc.StartTime).TotalMinutes
    ("pid $PID ws={0}MB pm={1}MB handles={2} threads={3} uptime={4}min new60s={5}" -f `
        [int]($proc.WorkingSet64 / 1MB), [int]($proc.PrivateMemorySize64 / 1MB), `
        $proc.HandleCount, $proc.Threads.Count, $up, (NewNeighbors)) |
        Set-Content -Path $Beat -Encoding UTF8
    if (-not (PortUp)) {
        if (LauncherActive) {
            WLog "port $Port down but launcher_active.flag present - skip (launcher restarting)"
        } else {
            # 이중확인 — 순간적 재바인딩/런처 킬 직후 오탐 방지
            Start-Sleep -Seconds 5
            if (-not (PortUp) -and -not (LauncherActive)) {
                WLog "port $Port DOWN - restarting server"
                $py = Join-Path $Root "api\.venv\Scripts\python.exe"
                Start-Process -FilePath $py `
                    -ArgumentList "-m","uvicorn","api.main:app","--host","0.0.0.0","--port","$Port","--log-config","scripts\uvicorn_logging.json" `
                    -WorkingDirectory $Root -WindowStyle Hidden
                Start-Sleep -Seconds 20
                if (PortUp) { WLog "restart OK - port $Port listening" }
                else { WLog "restart FAILED - port $Port still down (check logs\server.log)" }
            }
        }
    }
    Start-Sleep -Seconds 15
}
