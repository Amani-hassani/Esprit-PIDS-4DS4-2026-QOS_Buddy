@echo off
setlocal

cd /d "%~dp0backend" || (
  echo [ERROR] Impossible d'acceder au dossier backend.
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Environnement virtuel absent. Creation en cours...
  py -3.11 -m venv .venv || (
    echo [ERROR] Echec creation venv avec py -3.11.
    echo [HINT] Verifie les versions disponibles: py -0p
    goto :fail
  )
)

call ".venv\Scripts\activate.bat" || (
  echo [ERROR] Activation du venv impossible.
  goto :fail
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (
  echo [ERROR] Installation des dependances backend echouee.
  goto :fail
)

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload || goto :fail
goto :eof

:fail
echo.
echo [STOP] Le script s'est arrete a cause d'une erreur.
pause
exit /b 1
