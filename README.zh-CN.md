<p align="center"><img src="src/side_galaxy/static/icon.svg" width="88" alt="Side Galaxy 标识"></p>
<h1 align="center">Side Galaxy · 侧视星系</h1>
<p align="center">One orbit. Many worlds.<br>模块化嵌入式多板实验与多核资源控制平台。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

一台服务器统一管理多块嵌入式开发板。上传实验代码、选择目标设备、配置资源，再通过 Web、CLI 或 MCP 运行实验并收集结果。

平台提供 Raspberry Pi 4 / Pi 5 板型配置，以及 Linux / KVM 执行模块。板型描述、系统配置和执行模块可独立扩展；模块在实验间热重载，运行中的任务保留固定版本。

## 功能

- **运行自己的代码：** ZIP 实验包声明准备步骤、启动命令、默认环境和输出文件，每次实验可追加参数、覆盖环境变量。
- **集中管理多板：** 能力探测、管理核心保留、原子批量准入、逐板租约、幂等提交、取消与恢复。
- **配置运行资源：** Linux 进程绑核和地址空间限制；KVM 在线 vCPU 绑核、QEMU Guest Agent 传包执行、统计采集及原配置恢复。
- **追溯每次实验：** 保存制品与模块摘要、资源计划、退出码、最终日志、输出文件和清理证据。
- **连接人与 AI：** Web 控制台、可脚本化 CLI 与 MCP stdio 工具共用 API 和鉴权规则。
- **批量部署：** 容器化控制服务器，以及面向 Debian 系 Linux 板端代理的 Ansible 部署入口。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```sh
uv sync --frozen
uv run sg serve --demo
```

打开 [localhost:7980](http://127.0.0.1:7980)，进入控制台。模拟板卡生成 synthetic 数据，不执行上传的代码。

在另一个终端中运行：

```sh
uv run sg boards
uv run sg preflight examples/pi-contention.json
uv run sg submit examples/pi-contention.json --key first-experiment
uv run sg batches
```

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

## AI 接入

在兼容 MCP 的客户端中设置运行命令 `sg mcp`，通过环境变量提供 `SG_SERVER` 和 `SG_TOKEN`。默认提供查询与预检；使用 `sg mcp --allow-writes` 和 operator token，可上传制品、提交实验、取消批次或重载模块。

## 文档

- [运行、部署与 AI 连接](docs/operations.md)
- [实验代码、依赖与结果](docs/workloads.md)
- [Linux / KVM 执行与 guest 配置](docs/kvm-workloads.md)
- [模块开发与热重载](docs/modules.md)
- [架构与资源模型](docs/research.md)
- [测试与检查](docs/testing.md)
- [品牌与界面规范](docs/brand.md)

## 许可

[MIT](LICENSE)。随附第三方组件保留原始许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
