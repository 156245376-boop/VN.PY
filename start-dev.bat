@echo off
REM 一键启动开发环境:后端(8180) + 前端(5173),各开一个窗口。
REM 双击本文件即可;两个窗口分别是后端和前端,关闭窗口即停止对应服务。
setlocal
set ROOT=%~dp0
echo 正在启动后端 (http://127.0.0.1:8180) ...
start "cao-backend" cmd /k ""%ROOT%run-backend.bat""
echo 正在启动前端 (http://127.0.0.1:5173) ...
start "cao-frontend" cmd /k ""%ROOT%run-frontend.bat""
echo.
echo 已启动。请在浏览器打开: http://127.0.0.1:5173
echo (后端 API 文档: http://127.0.0.1:8180/docs)
endlocal
