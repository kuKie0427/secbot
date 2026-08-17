# Web UI 构建与部署

Phase 6 移植的 `web/`（Vite + React，源自 TS 仓）由 FastAPI 直接托管，无需独立静态服务器。

## 开发模式（前后端分离）

```bash
make dev-server   # 后端 :8000（热重载）
make dev-web      # 前端 :5173（vite dev，/api 代理 → :8000）
```

浏览器访问 http://localhost:5173。

## 生产模式（单进程托管）

```bash
make build-web    # web/ npm ci + build → 拷入 secbot_web/dist
make server       # uvicorn :8000，根路径出 UI
```

dist 解析顺序（`router/main.py::_resolve_web_dist`）：

1. `SECBOT_WEB_DIST` 环境变量覆盖
2. 源码仓 `web/dist`（make build-web 产出）
3. wheel 安装的 `secbot_web/dist`（pip 安装包内）

dist 缺失时后端正常启动、仅跳过静态托管（日志提示）。

## 打包（wheel）

- `secbot_web/dist` 通过 `[tool.setuptools.package-data]` 进入 wheel（见 pyproject.toml）
- **dist 不进 git**（.gitignore `dist/`）；CI（.github/workflows/ci.yml `web` job）负责构建并上传 artifact
- release 工作流在 `python -m build` 前先构建前端并装入 secbot_web/dist

验证 wheel 内容：

```bash
python -m build && unzip -l dist/*.whl | grep secbot_web
```

## 与 TS 仓的差异

| 项 | TS 仓 | Python 仓 |
|---|---|---|
| dist 进 git | 是 | 否（CI 构建，有意偏离——记录于 Phase 6 PR） |
| 托管 | Nest ServeStatic | FastAPI catch-all + SPA fallback |
| 前后端端口 | 8000/5173 | 8000/5173（一致） |
