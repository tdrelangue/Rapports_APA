@echo off
REM Compilation de l'application APA_Email en .exe
pyinstaller -F -w -n Rapporteur_APA --icon "assets/icon.ico" --add-data "assets;assets" APA_Email.py

REM Copie des fichiers de configuration modifiables
xcopy .env dist\APA_Email\ /Y
xcopy templates dist\APA_Email\templates\ /E /I /Y

echo.
echo === Build terminé ===
pause
