<p align="center"><img src="src/side_galaxy/static/icon.svg" width="88" alt="Side Galaxy 标识"></p>
<h1 align="center">Side Galaxy · 侧视星系</h1>
<p align="center">One orbit. Many worlds.<br>模块化嵌入式多板实验与多核资源控制平台。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

一台服务器统一管理多块嵌入式开发板。上传实验代码、选择目标设备、配置资源，再通过 Web、CLI 或 MCP 运行实验并收集结果。

平台提供 Raspberry Pi 4 / Pi 5 板型配置，以及 Linux / KVM 执行模块。板型描述、系统配置和执行模块可独立扩展；模块在实验间热重载，运行中的任务保留固定版本。

## 功能

- **运行自己的代码：** ZIP 实验包声明准备步骤、启动命令、默认环境和输出文件，每次实验可追加参数、覆盖环境变量。
- **集中管理多板：** 能力探测、管理核心保留、原子批量准入、持久等待队列、逐目标租约、幂等提交、取消与恢复。
- **携带离线环境：** 分发准备好的 guest 镜像与依赖，每次实验使用全新写入层，无需重启板子。
- **配置运行资源：** Linux 进程绑核和地址空间限制；KVM 在线 vCPU 绑核、QEMU Guest Agent 传包执行、统计采集及原配置恢复。
- **追溯每次实验：** 保存制品、环境与模块摘要、资源计划、运行中输出、退出码、最终日志、输出文件和清理证据。
- **连接人与 AI：** Web 控制台、可脚本化 CLI 与 MCP stdio 工具共用 API 和鉴权规则。
- **批量部署：** 容器化控制服务器，以及面向 Debian 系 Linux 板端代理的 Ansible 部署入口。

## 架构

C++20 核心通过 SQLite 管理板卡注册、能力准入、原子批次、租约与任务状态迁移。Python 将 HTTP、CLI 和 MCP 桥接到该核心，处理制品 I/O，并承载执行插件协议。

原生核心是必需组件，不提供 Python 调度回退。板型和系统支持仍通过配置清单与执行模块扩展。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。从源码安装还需 CMake 3.20+、支持 C++20 的编译器和 SQLite 开发头文件。

| 平台 | 构建依赖 |
|---|---|
| macOS | Xcode Command Line Tools（`xcode-select --install`）及 CMake |
| Debian / Ubuntu | `sudo apt-get install build-essential cmake libsqlite3-dev` |

`uv sync` 会构建必需的原生库。工具链配置与平台安装包说明见[原生构建指南](docs/native-build.md)。

```sh
uv sync --frozen
uv run sg serve
```

打开 [localhost:7980](http://127.0.0.1:7980) 进入控制台。默认工作区只显示真实接入的设备；使用 `sg lab up` 接入本地 Linux，或开启控制台的「演示模式」查看模拟示例。本地访问仅限 loopback，远程监听需要 `SG_TOKEN`。

在另一个终端中运行：

```sh
uv run sg boards
uv run sg lab up
uv run sg batches
```

## 没有开发板也能开发

启动控制服务后，在另一个终端运行 `uv run sg lab up`。本地 QEMU 环境会启动 ARM64 Linux，在 guest 内构建原生核心并注册设备，真正编译、运行上传的实验。依赖和配置见[本地实验指南](docs/local-lab.md)。

选择其他目标即可复用原实验包和参数，也可运行 `sg replay SOURCE_BATCH_ID --boards TARGET_BOARD_ID --key deployment-001`。准入前会检查声明的架构、操作系统和命令要求。

## 实验控制

使用 `sg preflight plan.json --enqueue` 和 `sg submit plan.json --enqueue --key experiment-001` 等待忙碌目标。每个执行目标同时运行一个实验，不同目标可并行执行。等待中的批次不占用资源，通过重新检查后一次性获得全部所需租约。控制台默认开启排队；`waiting` 表示等待资源，`queued` 表示已分配资源、等待代理启动。队列位置不是预计等待时间。

使用 `sg logs RUN_ID --follow` 跟踪运行中输出，按 Ctrl+C 停止查看。实时日志限制保留量，并明确提示截断；最终 stdout/stderr 和结果独立于实时传输保存。

`sg reload BOARD_ID` 在当前实验结束后重载；`sg reload BOARD_ID --force` 会先中断实验再重载。控制台提供对应操作与进度、错误反馈。受管 QEMU 支持 `sg lab restart` 和 `sg lab restart --force`，通过 `sg labs` 查看完成状态；重启保留磁盘与设备身份。

演示开关会启动或停止示例代理，隐藏模拟设备及纯模拟历史，不删除记录。CLI 使用 `sg workspace --demo on|off`；`sg serve --demo` 可明确指定以演示模式启动。

## 使用自己的实验

实验 ZIP 的根目录包含 `experiment.json`、代码及输入文件：

```json
{
  "schema": 1,
  "name": "latency-benchmark",
  "setup": [],
  "run": ["python3", "benchmark.py"],
  "env": {"SAMPLES": "1000"},
  "outputs": ["results.json"]
}
```

打包并上传仓库中的示例：

```sh
mkdir -p .data
uv run sg pack examples/hello-workload --output .data/hello-workload.zip
uv run sg artifact-upload .data/hello-workload.zip
```

在控制台选择上传的版本与目标板卡，或通过 CLI / MCP 提交 JSON 计划。实验代码在已连接的 Linux 代理或配置好的 KVM guest 中运行；计划、依赖、日志与结果下载见[实验指南](docs/workloads.md)。

## 准备离线环境

在 guest 中预装 Python、QEMU Guest Agent 和实验所需工具，然后将环境与实验代码分别打包上传：

```sh
uv run sg environment-pack prepared-environment --output .data/environment.zip
uv run sg environment-upload .data/environment.zip
uv run sg environments
```

在控制台选择环境，或将其摘要填入实验计划的 `environment_sha256`。`qemu-environment` 目标需要管理员预装 QEMU，并在 Linux 上提供 KVM 访问权限。板子从控制服务器获取包，无需访问互联网。每次运行和复用实验都会创建全新写入层，清理 guest 即可重置，无需重启板子。镜像准备见[环境指南](docs/environments.md)，私有离线部署见[部署指南](docs/operations.md)。首次在物理板已有系统中运行实验可使用 `linux-process`。

## AI 接入

在兼容 MCP 的客户端中设置运行命令 `sg mcp`，通过环境变量提供 `SG_SERVER` 和 `SG_TOKEN`。默认提供查询与预检，包括 `list_environments` 和 `get_run_logs`。使用 `sg mcp --allow-writes` 和 operator token，可上传实验包或环境包、通过 `run_experiment(..., enqueue=true)` 提交实验、取消批次或重载模块。

## 文档

详细文档使用英文编写。

- [QEMU 本地实验与目标迁移](docs/local-lab.md)
- [原生核心构建与打包](docs/native-build.md)
- [运行、部署与 AI 连接](docs/operations.md)
- [实验代码、依赖与结果](docs/workloads.md)
- [准备离线实验环境](docs/environments.md)
- [Linux / KVM 执行与 guest 配置](docs/kvm-workloads.md)
- [模块开发与热重载](docs/modules.md)
- [架构与资源模型](docs/research.md)
- [测试与检查](docs/testing.md)
- [品牌与界面规范](docs/brand.md)

## 许可

[MIT](LICENSE)。随附第三方组件保留原始许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
