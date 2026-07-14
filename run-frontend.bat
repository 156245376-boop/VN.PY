@echo off
cd /d "%~dp0frontend"
node "node_modules\vite\bin\vite.js" --host 127.0.0.1 --port 5173 --strictPort > "%~dp0frontend\vite.out.log" 2>&1
