# BioJob Agent 独立运行环境兼容修复设计

## 背景与故障

BioJob Agent 0.1.0 默认解析到 `%LOCALAPPDATA%\hermes`，因此会复用用户电脑上已有的 Hermes checkout。当前故障机器上的 checkout 固定在 2026-07-13 的提交 `f96b2e6ef7`，其中没有 `/api/health` 和 BioJob API；新版桌面壳对 `/api/health` 的探测被旧鉴权中间件拒绝，最终显示 `401 Unauthorized`。

这不是用户的模型 API Key 错误。只绕过健康检查也不完整，因为旧运行时仍缺少岗位、画像、简历和投递表接口。

## 目标

- BioJob Agent 始终使用自己管理的运行时，不读取或修改既有 Hermes checkout。
- 在 Windows 上默认使用 `%LOCALAPPDATA%\BioJob Agent` 作为 BioJob 的 `HERMES_HOME`，运行时位于其 `hermes-agent` 子目录。
- 允许显式测试/开发覆盖，但不继承机器级 `HERMES_HOME`，避免旧 Hermes 再次劫持正式 BioJob 应用。
- 首次启动时安全迁移旧目录下已有的 BioJob 数据；仅复制 BioJob 专属数据，绝不复制 Hermes 的配置、密钥、聊天或认证信息。
- 安装、修复、卸载、日志和用户文档全部指向新的 BioJob 目录。

## 方案

### 运行时与数据目录

新增一个可独立测试的桌面路径解析模块。正式 BioJob 构建的默认根目录为：

```text
Windows: %LOCALAPPDATA%\BioJob Agent
macOS:   ~/Library/Application Support/BioJob Agent/runtime
Linux:   ~/.local/share/biojob-agent
```

自动化测试和开发工具仍可通过专用的显式覆盖参数传入临时目录。正式应用不采用系统或旧 Hermes 安装设置的 `HERMES_HOME`。

### 数据迁移

迁移器只处理旧根目录的 `biojob` 子目录：

```text
%LOCALAPPDATA%\hermes\biojob
  -> %LOCALAPPDATA%\BioJob Agent\biojob
```

规则：

1. 新目录不存在且旧目录存在时才迁移。
2. 使用同一磁盘上的临时目录先复制并校验，再原子改名发布。
3. 旧目录保留，作为可恢复备份；迁移不执行删除。
4. 若迁移失败，记录不含敏感值的错误并停止本地后端启动，向用户提供重试，不启动一个缺数据的空实例。
5. `config.yaml`、`.env`、`auth.json`、sessions、skills 和旧 checkout 均不迁移。

### 安装与修复

首次安装在 BioJob 独立根目录中克隆/安装打包时固定的 BioJob 仓库提交。已有但不兼容的 BioJob 独立运行时不能仅凭“可 import”被接受；探测必须验证 BioJob 后端能力。修复安装仅重建 BioJob 的独立运行时，不接触 `%LOCALAPPDATA%\hermes`。

### 兼容与错误处理

- 不把旧 `/api/health` 的 401 当作模型鉴权失败。
- 若独立运行时缺少 BioJob 能力，进入明确的“需要修复安装”状态。
- 日志显示实际使用的 BioJob 根目录、运行时提交和能力探测结果，但不输出任何 token、密码或 API Key。

## 测试策略

严格执行 RED-GREEN-REFACTOR：

1. 路径解析单元测试：Windows 默认目录与测试覆盖优先级。
2. 数据迁移测试：首次复制、目标已存在时幂等、失败不产生半成品、敏感文件不迁移。
3. 运行时选择测试：旧 Hermes 即使可 import 也不能成为 BioJob 的 active runtime。
4. 启动集成测试：模拟同时存在旧 Hermes 与全新 BioJob home，确认子进程的 `HERMES_HOME` 和 runtime root 都指向 BioJob。
5. 现有桌面测试、BioJob 后端测试、格式检查和 Windows 打包检查全部通过。
6. 使用临时的旧 Hermes 环境运行打包产物，验证启动、BioJob API 和 WebSocket；不得读写用户真实数据。

## 验收标准

- 当前机器的旧 `%LOCALAPPDATA%\hermes\hermes-agent` 保持原提交和文件不变。
- 新安装包在旧 Hermes 存在时仍能完成启动，不再出现 `/api/health` 401。
- BioJob 岗位、画像、简历和带跳转链接的投递表接口可用。
- 安装程序、便携包与中文使用指南均明确指向 BioJob 独立目录。
- 重新发布可下载的 Windows 产物，并在本机完成一次隔离验证。
