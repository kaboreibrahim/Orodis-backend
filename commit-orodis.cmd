@echo off
rem Commit et push du depot orodis-backend. Journal : commit-journal.txt
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0commit-journal.txt"
>>".git\info\exclude" echo commit-orodis.cmd
>>".git\info\exclude" echo commit-message.txt
>>".git\info\exclude" echo commit-journal.txt
(
echo === orodis-backend ===
git add -A
echo --- Fichiers prets a etre commites :
git status --short
) > "%LOG%" 2>&1
git diff --cached --name-only | findstr /R /I "\.env$ \.env\.local$ settings\.local\.json$ \.keystore$ \.jks$" >nul
if not errorlevel 1 (
  git reset -q
  echo ARRET : un fichier secret etait dans la liste, rien n a ete commite.>> "%LOG%"
  goto fin
)
(
echo --- Commit :
git commit -F commit-message.txt
echo --- Push :
git push -u origin HEAD
echo --- Etat final :
git status -sb
git log --oneline -3
echo === FIN ===
) >> "%LOG%" 2>&1
:fin
type "%LOG%"
pause
