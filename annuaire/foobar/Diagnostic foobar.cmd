@echo off
chcp 65001 >nul
rem Rassemble les informations utiles au dépannage du lien foobar et les dépose à côté de ce fichier.
set "OUT=%~dp0diagnostic-%COMPUTERNAME%.txt"
call :rapport > "%OUT%" 2>&1 || set "OUT=%USERPROFILE%\Desktop\diagnostic-foobar.txt"
if not exist "%OUT%" call :rapport > "%OUT%" 2>&1
echo Diagnostic enregistré : %OUT%
pause
exit /b 0
:rapport
echo === %DATE% %TIME% - %COMPUTERNAME% / %USERNAME%
echo === Windows
ver
echo === Lien foobar (compte utilisateur)
reg query "HKCU\Software\Classes\foobar" /s
echo === Lien foobar (vue globale)
reg query "HKCR\foobar" /s
echo === Navigateurs : liens autorisés / choix d'application pour foobar:
reg query "HKCU\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\foobar" /s
echo === foobar2000.exe
if exist "%ProgramFiles%\foobar2000\foobar2000.exe" (echo trouvé : %ProgramFiles%\foobar2000\foobar2000.exe) else echo absent de %ProgramFiles%\foobar2000
if exist "%ProgramFiles(x86)%\foobar2000\foobar2000.exe" echo trouvé : %ProgramFiles(x86)%\foobar2000\foobar2000.exe
echo === Script installé
dir "%LOCALAPPDATA%\foobar-lien"
echo === Journal des clics
type "%LOCALAPPDATA%\foobar-lien\journal.txt"
echo === Ce dossier
echo %~dp0
echo === Lecteurs réseau
net use
echo === Associations .cmd / .ps1
assoc .cmd
assoc .ps1
exit /b 0
