@echo off
chcp 65001 >nul
rem Installe le lien foobar: de l'annuaire pour l'utilisateur courant (sans droits administrateur).
set "DEST=%LOCALAPPDATA%\foobar-lien"
if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0foobar-lien.ps1" "%DEST%\foobar-lien.ps1" >nul || goto :erreur
reg add "HKCU\Software\Classes\foobar" /ve /d "URL:foobar" /f >nul || goto :erreur
reg add "HKCU\Software\Classes\foobar" /v "URL Protocol" /d "" /f >nul || goto :erreur
reg add "HKCU\Software\Classes\foobar\shell\open\command" /ve /d "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%DEST%\foobar-lien.ps1\" \"%%1\"" /f >nul || goto :erreur
echo Lien foobar installé. Les boutons ▶ de l'annuaire ouvrent maintenant foobar2000.
pause
exit /b 0
:erreur
echo Échec de l'installation.
pause
exit /b 1
