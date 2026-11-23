$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать окружение Python.' }
    & .venv/Scripts/python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
}
& .venv/Scripts/python.exe manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Не удалось применить миграции.' }
& .venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
