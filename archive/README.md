# 旧成果封存

`legacy-vnpy-2026-10-15.zip` 保存切换前的 98 个源文件，共 625,594 字节，
包括全部未提交与未跟踪的旧成果。整体 SHA256 见同名 `.sha256` 文件。
包内 `project/` 保留原路径和字节；`metadata/` 含逐文件清单、原 HEAD、Git 状态、补丁与排除说明。

旧系统仅完成部分基础逻辑，交易链路未完成，8 个市场事实用例仍待核对。
包不包含 Git 历史、虚拟环境、真实凭证或运行数据；原 `.git` 与旧环境保留原位。
默认不读取或解压。需要取回单项能力时，先验证并恢复到工作区外的空目录：

```powershell
& .\.venv-tqsdk\Scripts\python.exe -I -B .\tools\verify_archive.py `
  --archive .\archive\legacy-vnpy-2026-10-15.zip `
  --sha256-file .\archive\legacy-vnpy-2026-10-15.sha256 `
  --extract-to "$env:TEMP\qf-legacy-review"
```

省略 `--extract-to` 可只验包。目标非空或位于当前工作区内时拒绝恢复。
恢复后先核对并选择所需文件，不整体覆盖回新主线，不恢复旧项目指令为默认规则。
