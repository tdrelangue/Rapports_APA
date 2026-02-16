@echo off
REM Compilation de l'application APA_Email en .exe
python -m pip install -r requirements.txt
python -m PyInstaller -F -w -n "Rapporteur APA" --icon "assets/icon.ico" --add-data "assets;assets" APA_Email.py

REM Copie des fichiers de configuration modifiables
xcopy templates dist\templates\ /E /I /Y
xcopy assets dist\assets\ /E /I /Y
xcopy Protégés dist\Protégés\ /E /I /Y
xcopy .env dist\ /E /I /Y

echo.
echo === Build terminé ===
pause
