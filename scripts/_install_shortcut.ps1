# Install (or refresh) "DB OCIO Dashboard.lnk" on the user's Desktop.
# Target = scripts\launch_dashboard.bat in the same repo as this script.
$root    = Split-Path -Parent $PSScriptRoot
$target  = Join-Path $PSScriptRoot "launch_dashboard.bat"
$desktop = [Environment]::GetFolderPath('Desktop')
$link    = Join-Path $desktop "DB OCIO Dashboard.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($link)
$sc.TargetPath       = $target
$sc.WorkingDirectory = $root
$sc.IconLocation     = "shell32.dll,13"
$sc.Description      = "DB OCIO Dashboard (FastAPI + React Vite)"
$sc.WindowStyle      = 1
$sc.Save()

if (Test-Path $link) {
    Write-Host "[OK] Created: $link" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Shortcut not created" -ForegroundColor Red
    exit 1
}
