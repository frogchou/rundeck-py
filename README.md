# RunDeck-Py

一个基于 FastAPI 的轻量级“部署监控/运维脚本执行控制台”。提供安全的脚本执行、实时输出、可控命令白名单，并自带简洁的前端页面。

## 功能特性
- 单页 Web 控制台：执行默认脚本或自定义脚本/命令。
- 实时输出：使用 Server-Sent Events 推送 stdout/stderr，支持滚动查看和复制。
- 任务控制：同一时间只允许一个任务，支持停止正在运行的任务。
- 安全防护：
  - 仅允许 `/home/fix` 目录下的可执行脚本。
  - 命令模式默认启用严格白名单；可通过配置开启任意命令（存在风险）。
  - 禁用 `shell=True`，输出做基础转义，减少注入/XSS 风险。

## 目录结构
```
app/                # 核心 FastAPI 应用
static/             # 前端静态资源 (CSS/JS)
templates/          # Jinja2 模板
deploy/systemd/     # systemd 启动示例
tests/              # 预留测试目录
.env.example        # 环境变量示例
requirements.txt    # Python 依赖
README.md
```

## 快速开始
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 根据需要调整 .env 后启动
uvicorn app.main:app --host 0.0.0.0 --port 8000
```


浏览器访问 `http://<host>:8000/`，使用密码登录（默认 `frogchou`，请在 `.env` 中修改）。


## 配置项（.env）
- `HOST`：监听地址，默认 `0.0.0.0`。
- `PORT`：监听端口，默认 `8000`。
- `DEFAULT_SCRIPT`：默认脚本路径，默认 `/home/fix/dev.sh`。
- `ALLOWED_SCRIPT_ROOT`：脚本白名单根目录，默认 `/home/fix`。
- `ALLOW_ARBITRARY_COMMAND`：是否允许任意命令，默认 `false`（安全起见保持关闭）。
- `COMMAND_WHITELIST`：命令白名单，逗号分隔，默认 `echo,ls,cat,tail,grep,systemctl status,journalctl -u`。
- `ACCESS_PASSWORD`：访问控制密码，默认 `frogchou`。访问页面或调用 API 时需要先登录。


> ⚠️ **安全提示**：
> - 仅当你完全信任调用者和环境时再将 `ALLOW_ARBITRARY_COMMAND` 设为 `true`。开启后意味着可以执行任意命令，存在极大风险。
> - 建议使用受限的系统用户运行本服务，并限制网络访问。
> - 登录密码请及时修改并妥善保护，避免泄露。



## API
- `GET /`：返回控制台页面。
- `POST /api/run`：启动执行，body `{ "mode": "script"|"command", "value": "..." }`。
- `GET /api/stream/{task_id}`：SSE 输出流，先推送历史缓冲再推送增量。
- `POST /api/stop/{task_id}`：停止任务。

## 运行机制
- 使用 `asyncio.create_subprocess_exec` 执行命令，禁止 `shell=True`（除非显式允许任意命令）。
- 单任务模式：已有任务运行时会拒绝新的执行请求。
- 输出缓冲限制为 ~5MB，超出后丢弃最早内容。
- 停止任务时尝试发送进程组信号（`start_new_session=True` + `os.killpg`）。

## systemd 示例
`deploy/systemd/rundeck-py.service`
```ini
[Unit]
Description=RunDeck-Py Service
After=network.target

[Service]
WorkingDirectory=/opt/rundeck-py
ExecStart=/opt/rundeck-py/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
EnvironmentFile=/opt/rundeck-py/.env
Restart=on-failure
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

## 测试
预留 `tests/` 目录，可根据需要补充单元测试或集成测试。
