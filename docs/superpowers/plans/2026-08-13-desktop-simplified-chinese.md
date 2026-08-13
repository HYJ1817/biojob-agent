# BioJob Agent Simplified Chinese Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前安装的 BioJob Agent 整体界面切换为简体中文，同时保持旧 Hermes 配置和其他 BioJob 设置不变。

**Architecture:** 复用现有 `display.language` 国际化配置，不修改应用代码。仅在 BioJob 独立的 `config.yaml` 的 `display` 映射中加入 `language: zh`，重启桌面应用后验证中文界面和交互。

**Tech Stack:** YAML、BioJob Agent 内置 i18n、Windows PowerShell、Electron

---

### Task 1: 更新独立 BioJob 语言配置

**Files:**
- Modify: `%LOCALAPPDATA%\BioJob Agent\config.yaml`

- [ ] **Step 1: 检查当前配置边界**

运行只读命令，确认 `display` 当前没有 `language`，并记录用户级 `HERMES_HOME`：

```powershell
Select-String -LiteralPath "$env:LOCALAPPDATA\BioJob Agent\config.yaml" -Pattern '^display:'
[Environment]::GetEnvironmentVariable('HERMES_HOME', 'User')
```

预期：配置文件存在，用户级 `HERMES_HOME` 指向 `%LOCALAPPDATA%\hermes`。

- [ ] **Step 2: 保留其他字段并加入简体中文配置**

在现有 `display:` 映射下加入：

```yaml
display:
  language: zh
```

不得改写 `display` 下的其他键，也不得修改旧 Hermes 配置文件。

- [ ] **Step 3: 验证 YAML 和配置值**

使用 BioJob 自己的 Python 环境解析 YAML：

```powershell
& "$env:LOCALAPPDATA\BioJob Agent\hermes-agent\venv\Scripts\python.exe" -c "import os,yaml; p=os.path.join(os.environ['LOCALAPPDATA'],'BioJob Agent','config.yaml'); d=yaml.safe_load(open(p,encoding='utf-8')); assert d['display']['language']=='zh'; print('language=zh')"
```

预期：输出 `language=zh`。

### Task 2: 重启并验收中文界面

**Files:**
- Verify: `%LOCALAPPDATA%\BioJob Agent\logs\desktop.log`

- [ ] **Step 1: 重启正式安装版本**

关闭当前 `BioJob-Agent.exe`，再从正式安装路径启动，等待后端日志出现 `Hermes backend is ready`。

- [ ] **Step 2: 验证中文与交互**

确认主导航、设置和 BioJob 工作台显示简体中文；依次打开“候选岗位”“投递管理”“个人事实”“岗位来源”，确认点击切换有效。

- [ ] **Step 3: 验证隔离与健康状态**

请求运行日志公布端口的 `/api/health`，预期返回 `ok: true`。再次读取用户级 `HERMES_HOME`，预期仍为 `%LOCALAPPDATA%\hermes`。

- [ ] **Step 4: 提交计划与报告结果**

仓库只提交本计划文档；用户机器上的语言配置属于本地状态，不提交到 Git。
