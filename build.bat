@echo off
REM Build FaxSend.exe from faxwatcher.py. Run this from the folder containing faxwatcher.py.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install it from https://www.python.org/downloads/ and run this again.
    pause
    exit /b 1
)

py -m pip install --upgrade requests pyinstaller pypdfium2 pillow
if errorlevel 1 goto :fail

REM --collect-all bundles the PDF engine (pdfium.dll) inside the exe
py -m PyInstaller --onefile --console --clean --name FaxSend ^
    --collect-all pypdfium2 --collect-all pypdfium2_raw faxwatcher.py
if errorlevel 1 goto :fail

echo.
echo Built: %~dp0dist\FaxSend.exe
echo.
echo Next, for each customer:
echo   1. Copy config.template.ini to customers\NAME\config.ini and fill it in
echo   2. Run: make_package.bat NAME
echo   3. Send packages\FaxSend-NAME.zip to the customer
pause
exit /b 0

:fail
echo Build failed - see the messages above.
pause
exit /b 1
