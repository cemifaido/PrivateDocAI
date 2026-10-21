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
echo Fatto. Copia l'intera cartella dist\PrivateDocAI sul PC di destinazione
echo (senza averla mai avviata) e avvia PrivateDocAI.exe
pause
