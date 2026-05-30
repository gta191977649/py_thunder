# Contributing to PyThunder

感谢你愿意参与 PyThunder。

这个项目目前处于快速迭代阶段，我们优先欢迎以下类型的贡献：

- Bug 修复
- UI 细节优化
- 下载逻辑稳定性改进
- 跨平台兼容性修复
- 打包与发布流程完善
- 文档补充和示例完善

## 开始之前

在提交代码前，建议先确认以下几点：

- 先阅读 [README.md](D:/dev/py_thunder/README.md)
- 如果修改较大，先开 issue 或先描述一下改动方向
- 保持改动聚焦，尽量一个 PR 只解决一类问题

## 本地开发环境

推荐使用 Python 3.11 或更高版本。

### 1. 创建虚拟环境

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
python -m pip install -r requirements.txt
```

如果你需要验证打包流程：

```bash
python -m pip install -r requirements-build.txt
```

### 3. 运行项目

```bash
python main.py
```

## 提交改动建议

我们鼓励尽量保持以下原则：

- 优先做小步、明确、可验证的修改
- 不要把无关格式化、重命名和逻辑改动混在同一个提交里
- 避免顺手改动与当前目标无关的文件
- 修改资源路径、打包脚本、平台相关逻辑时，尽量说明验证方式

## 代码风格

当前项目没有强绑定某个格式化工具，但请尽量遵守这些约定：

- 保持现有目录分层和模块职责清晰
- UI 层不要直接访问 aria2 或 SQLite
- 新增功能优先走 `DownloadManager` 这类中间层
- 命名清晰，避免缩写过度
- 注释只写必要信息，避免解释显而易见的代码

## 与 aria2 相关的约定

- 不要把平台二进制直接提交进仓库
- 对应平台的 `aria2c` 应放在 `resources/aria2/<platform>/`
- 仓库默认忽略这些二进制文件
- 如果你的改动依赖某个 aria2 行为，请在 PR 描述里写清楚测试平台

## 提交前自检

提交前建议至少完成下面这些检查：

```bash
python -m compileall app core services storage ui scripts main.py
```

如果你改了打包逻辑，也建议补一轮构建验证：

Windows:

```powershell
.\build.ps1 -Mode portable -Clean
```

通用方式:

```bash
python scripts/build_release.py --mode portable --clean
```

## Pull Request 建议内容

提交 PR 时，建议说明：

- 改了什么
- 为什么要改
- 是否影响 Windows / macOS / Linux
- 是否影响打包结果
- 你本地做了哪些验证

一个简单示例：

```text
## Summary
- fix packaged resource path lookup for PyInstaller
- improve Windows portable build docs

## Verification
- python main.py
- python -m compileall app core services storage ui scripts main.py
- .\build.ps1 -Mode portable -Clean
```

## 文档与变更记录

- 对用户可见的行为变化，请同步更新 `README.md`
- 对值得记录的版本改动，请同步更新 `CHANGELOG.md`

## 行为准则

请保持讨论友善、直接、尊重事实。我们欢迎不同意见，但希望所有讨论都围绕问题本身展开。

感谢你的贡献。
