@echo off
REM Build a customer zip: make_package.bat <customername>
REM Needs dist\FaxSend.exe (run build.bat) and customers\<customername>\config.ini
cd /d "%~dp0"
if "%~1"=="" (
    echo Usage: make_package.bat customername
    echo   Put the filled-in config in customers\customername\config.ini first
    echo   ^(copy config.template.ini^)
    exit /b 1
)
set CUST=%~1
if not exist "dist\FaxSend.exe" (
    echo dist\FaxSend.exe not found - run build.bat first
    exit /b 1
)
if not exist "customers\%CUST%\config.ini" (
    echo customers\%CUST%\config.ini not found - copy config.template.ini there and fill it in
    exit /b 1
)
findstr /c:"PUT_URL_HERE" /c:"PUT_API_KEY_HERE" /c:"PUT_FAX_UUID_HERE" "customers\%CUST%\config.ini" >nul
if not errorlevel 1 (
    echo customers\%CUST%\config.ini still has PUT_URL_HERE, PUT_API_KEY_HERE or PUT_FAX_UUID_HERE - fill it in
    exit /b 1
)
findstr /r /i /c:"^hostname *= *[a-z0-9]" "customers\%CUST%\config.ini" >nul
if errorlevel 1 (
    echo customers\%CUST%\config.ini has no hostname - fill it in
    exit /b 1
)

echo Checking the settings against the server...
dist\FaxSend.exe --test-api --base-dir "customers\%CUST%"
if errorlevel 1 (
    echo.
    echo The settings did not work - no zip was made.
    exit /b 1
)

set STAGE=packages\%CUST%
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
copy /y "dist\FaxSend.exe" "%STAGE%\" >nul
copy /y "customers\%CUST%\config.ini" "%STAGE%\" >nul
copy /y "README-customer.txt" "%STAGE%\README.txt" >nul
if exist "packages\FaxSend-%CUST%.zip" del "packages\FaxSend-%CUST%.zip"
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath 'packages\FaxSend-%CUST%.zip'"
rmdir /s /q "%STAGE%"
echo.
echo Created packages\FaxSend-%CUST%.zip
