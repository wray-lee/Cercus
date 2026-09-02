@echo off
REM Run Cercus and redirect console output to a log file
echo Starting Cercus Dashboard...
echo Log will be saved to startup.log

python main.py > startup.log 2>&1
