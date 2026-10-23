@echo off
chcp 65001 >nul
rem Retire le lien foobar: de l'annuaire.
reg delete "HKCU\Software\Classes\foobar" /f >nul 2>&1
rmdir /s /q "%LOCALAPPDATA%\foobar-lien" 2>nul
echo Lien foobar retiré.
pause
