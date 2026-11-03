@echo off
title Build PrivateDoc AI
echo Creazione dell'eseguibile (cartella dist\PrivateDocAI)...
python -m PyInstaller --noconfirm --clean PrivateDocAI.spec
if errorlevel 1 (
    echo Build fallita.
    pause
    exit /b 1
)
echo.
echo Controllo che la cartella non contenga password, pratiche o profili del browser...
python check_dist.py dist\PrivateDocAI
if errorlevel 1 (
    echo.
    echo CONTROLLO FALLITO: non distribuire la cartella. Non avviare l'eseguibile dentro dist\PrivateDocAI:
    echo copialo prima altrove.
    pause
    exit /b 1
)
echo.
echo Creazione dell'installer (richiede Inno Setup 6)...
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo Inno Setup non trovato: installer non creato. Installalo da https://jrsoftware.org/isdl.php
    echo In alternativa copia l'intera cartella dist\PrivateDocAI sul PC di destinazione
    echo senza averla mai avviata, e avvia PrivateDocAI.exe
    pause
    exit /b 0
)
"%ISCC%" installer\PrivateDocAI.iss
if errorlevel 1 (
    echo Creazione dell'installer fallita.
    pause
    exit /b 1
)
echo.
echo Fatto. L'installer e' nella cartella release\ PrivateDocAI-VERSIONE-Setup.exe.
pause
