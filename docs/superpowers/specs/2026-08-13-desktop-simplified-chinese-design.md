# BioJob Agent 简体中文切换设计

## 目标

将当前电脑上已安装的 BioJob Agent 整体界面切换为简体中文，包括主导航、BioJob 工作台、设置页、状态提示和首次配置界面。

## 方案

复用桌面应用现有的国际化能力，将 BioJob Agent 独立运行目录中的 `config.yaml` 配置项 `display.language` 设置为 `zh`。应用重启后由现有 `I18nProvider` 读取该配置并加载内置简体中文语言包。

不修改源代码中的默认语言，不硬编码中文，也不单独翻译 BioJob 页面。用户之后仍可通过“设置 → 外观 → 语言”切换其他语言。

## 隔离与安全

- 只修改 `%LOCALAPPDATA%\BioJob Agent\config.yaml`。
- 不修改 `%LOCALAPPDATA%\hermes` 中旧 Hermes 的配置、数据或环境变量。
- 保存配置前保留现有其他 YAML 字段，不重建或覆盖整个配置文件。
- 若配置写入失败，保持原文件不变并报告错误。

## 验收

1. 重启 BioJob Agent 后，主导航与 BioJob 工作台显示简体中文。
2. “候选岗位”“投递管理”“个人事实”“岗位来源”等入口可以正常点击。
3. 后端健康接口仍返回成功。
4. 用户级 `HERMES_HOME` 仍指向旧 Hermes 目录。
