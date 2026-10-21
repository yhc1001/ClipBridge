param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 이상을 설치하세요.' }
}
& $taskPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패' }
if (!$SkipTests) {
    & $taskPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw '테스트 실패 · EXE 빌드 중단' }
}
& $taskPython tools\make_icon.py
& $taskPython tools\build_exe.py
if ($LASTEXITCODE -ne 0) { throw 'EXE 빌드 실패' }
Write-Output '빌드 완료: dist\v1.3.0\ClipBridge.exe'
