@echo off
REM Run Cercus with full console output logged
echo Starting Cercus Dashboard...
echo Log will be saved to startup.log

python main.py 2>&1 | tee startup.log
