@echo off
setlocal

cd /d "%~dp0frontend" || (
  echo [ERROR] Impossible d'acceder au dossier frontend.
  goto :fail
)

where npm >nul 2>&1 || (
  echo [ERROR] npm introuvable. Installe Node.js 18+ puis reouvre le terminal.
  echo [HINT] Verifie avec: node -v ^&^& npm -v
  goto :fail
)

if not exist ".npm-cache" mkdir ".npm-cache"
set "npm_config_cache=%cd%\.npm-cache"

if not exist ".env" (
  copy ".env.example" ".env" >nul
)

if not exist "node_modules" (
  echo [INFO] Installation des dependances frontend...
  npm install || (
    echo [ERROR] npm install a echoue.
    goto :fail
  )
)

npm run dev || goto :fail
goto :eof

:fail
echo.
echo [STOP] Le script s'est arrete a cause d'une erreur.
pause
exit /b 1
