@echo off
rem ---------------------------------------------------------------------------------------------------------------
rem  Kiro AI: double-click this file to start everything.
rem
rem  The first run makes a private Python environment, installs the packages and builds the website. That takes a
rem  few minutes and needs the internet. Later runs start in a few seconds.
rem  Leave the window open while you use the app. Press Ctrl+C in it (or close it) to stop.
rem
rem    run.bat                 start the server and open the browser
rem    run.bat --no-browser    start it without opening the browser
rem    run.bat --port 8100     use a different port
rem    run.bat --rebuild       build the website again
rem    run.bat smoke           check a running server (start it in another window first)
rem    run.bat models          download the hand model that the image analysis needs
rem    run.bat sheet           draw what the analysis finds in the photos in ..\test-photos (pictures go to ..\debug)
rem    run.bat palm            try the palm lock on the photos in ..\palm-photos, one folder per person (pictures go to ..\debug\palm)
rem    run.bat palmeval        measure the palm lock on the class dataset in ..\palm-dataset (P01\1.jpg ... 7.jpg): FAR, FRR, accuracy, a confusion matrix (report goes to ..\debug\palm-eval)
rem    run.bat gemini          check the Gemini key and model, report and chat (also: --probe, --list-models, --quick)
rem    run.bat firebase        check the online database: the key in backend\secrets, one test write, read and delete
rem    run.bat live            a real report for the photos in ..\test-photos\person1, written with Gemini (run.bat live person2)
rem    run.bat preflight       everything that has to be true before a demonstration, checked in one go (it starts the app by itself)
rem    run.bat package         make the zip to hand in, in ..\submission (it builds the website first when that is out of date)
rem    run.bat fresh           start the newest zip in another folder, with no Node.js and no key, like a lecturer (takes minutes)
rem    run.bat evidence        the screenshots for the report: a browser goes through the app with your photos (into ..\evidence)
rem ---------------------------------------------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title Kiro AI

rem Find a Python that is 3.12 or newer.
set "PY="
for %%C in ("py -3.14" "py -3.13" "py -3.12" "py -3" "python") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=%%~C"
    )
)

if not defined PY (
    echo.
    echo   Python 3.12 or newer was not found on this computer.
    echo.
    echo   1. Install it from https://www.python.org/downloads/
    echo      ^(on the first screen, tick "Add python.exe to PATH"^)
    echo   2. Close this window, then double-click run.bat again.
    echo.
    pause
    exit /b 1
)

if /i "%~1"=="smoke" goto :smoke
if /i "%~1"=="models" goto :models
if /i "%~1"=="sheet" goto :sheet
if /i "%~1"=="palm" goto :palm
if /i "%~1"=="palmeval" goto :palmeval
if /i "%~1"=="gemini" goto :gemini
if /i "%~1"=="firebase" goto :firebase
if /i "%~1"=="live" goto :live
if /i "%~1"=="preflight" goto :preflight
if /i "%~1"=="package" goto :package
if /i "%~1"=="fresh" goto :fresh
if /i "%~1"=="evidence" goto :evidence

%PY% scripts\serve.py %*
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
    echo.
    echo   Kiro AI stopped with an error ^(code %CODE%^). The message above says why.
    echo.
    pause
)
exit /b %CODE%

:smoke
%PY% scripts\smoke.py %2 %3 %4 %5
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:models
%PY% scripts\fetch_models.py %2 %3 %4 %5
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:sheet
rem This one needs the packages that run.bat installs, so it runs inside the private environment.
if not exist "backend\.venv\Scripts\python.exe" (
    echo.
    echo   The private environment is not there yet. Run  run.bat  once first, wait until the server starts, then close it.
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\contact_sheet.py %2 %3 %4 %5
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:palm
rem The palm lock pilot (ICA 02). Like the contact sheet, it runs inside the private environment.
if not exist "backend\.venv\Scripts\python.exe" (
    echo.
    echo   The private environment is not there yet. Run  run.bat  once first, wait until the server starts, then close it.
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\palm_pilot.py %2 %3 %4 %5
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:palmeval
rem The palm lock evaluation (ICA 02): the numbers for the report. Same private environment as the pilot.
if not exist "backend\.venv\Scripts\python.exe" (
    echo.
    echo   The private environment is not there yet. Run  run.bat  once first, wait until the server starts, then close it.
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\palm_evaluate.py %2 %3 %4 %5 %6 %7
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:gemini
rem These two need the packages that run.bat installs, among them the Gemini library, so they make sure of them first.
%PY% scripts\serve.py --packages-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\check_gemini.py %2 %3 %4 %5 %6
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:live
%PY% scripts\serve.py --packages-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\live_report.py %2 %3 %4 %5 %6
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:preflight
rem This one needs the packages that run.bat installs, and a website that is up to date, so it makes sure of both first.
%PY% scripts\serve.py --prepare-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\preflight.py %2 %3 %4 %5 %6 %7 %8
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:package
rem The website in the zip has to be the one the sources make, so it is built first when it is out of date.
%PY% scripts\serve.py --prepare-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
%PY% scripts\package.py %2 %3 %4 %5 %6
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:fresh
rem This one makes its own private environment in the copy, so it needs nothing from this folder except Python.
%PY% scripts\fresh_copy.py %2 %3 %4 %5 %6 %7 %8
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:evidence
rem This one needs the packages that run.bat installs and a website that is up to date, and Playwright, which drives the browser.
%PY% scripts\serve.py --prepare-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" -c "import playwright" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Installing Playwright, the tool that drives the browser ^(once, about 40 MB^) ...
    "backend\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r backend\requirements-evidence.txt
    if errorlevel 1 (
        echo.
        echo   Playwright could not be installed. The lines above say why ^(often: no internet^).
        echo.
        pause
        exit /b 1
    )
)
"backend\.venv\Scripts\python.exe" scripts\capture_evidence.py %2 %3 %4 %5 %6 %7 %8 %9
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%

:firebase
rem This needs the packages that run.bat installs (Google's sign-in library among them), so it makes sure of them first.
%PY% scripts\serve.py --packages-only
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" scripts\check_firebase.py %2
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
