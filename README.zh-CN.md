# Resume Agent

[![CI](https://github.com/awbjcj/resume-agent/actions/workflows/ci-main.yml/badge.svg)](https://github.com/awbjcj/resume-agent/actions/workflows/ci-main.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)

[English](README.md) | 简体中文

Resume Agent 是一个本地优先、同时支持命令行和网页界面的求职工作流，也可以部署为多用户服务。它可以从招聘网站连接器、LinkedIn 或手动输入中获取职位，根据候选人的真实经历进行匹配评分，通过多智能体评审流程定制简历和求职信，将材料渲染为 PDF，并在工作区级 SQLite 数据库中跟踪完整的申请进度。

项目最重要的原则是 **事实锁定（fact-lock）**：定制简历中的每一条陈述都必须能够追溯到用户提供的真实事实。智能体可以重写和重新组织表达，但不能虚构经历。

> 本文档中的命令、配置键、API 路径和状态值保持英文，以便与程序界面和源码一致。

---

## 工作流程

职位会依次经过获取、筛选、人工批准、定制和申请跟踪。需要花费较高模型成本或改变持久状态的关键节点由用户决定。

```text
              ┌─ pull ───┐
  连接器      │          │
  LinkedIn    │  scrape  │
  手动输入    └─ addjob ─┘
                   │
                   ▼
   raw ─▶ extracted ─▶ filtered ─▶ shortlisted ─▶ approved ─▶ tailored ─▶ rendered
                          │            ▲   │           ▲           │
                       rejected     discover       用户批准    cover-letter

   申请状态：ready ─▶ submitted ─▶ interview ─▶ offer / rejected / closed
                                        ▲
                                sync-status 提议 Gmail 状态变更
```

| 阶段 | 命令或入口 | 作用 |
| --- | --- | --- |
| 获取职位 | `pull` / `scrape` / `addjob` | 从已启用的招聘来源、LinkedIn 或手动输入中写入职位，并按 URL 或职位描述去重。 |
| 发现与评分 | `discover` | 提取结构化职位要求，应用硬性筛选条件，并计算匹配度。 |
| 人工批准 | 网页界面或 `approve` | 只批准值得进入定制流程的职位。 |
| 定制简历 | `tailor` | 由写作智能体起草、评审面板批注，并循环修订到通过事实门禁。 |
| 求职信 | `cover-letter` | 根据事实锁定资料生成求职信，并进行确定性的来源校验。 |
| PDF 渲染 | `render` | 使用 Typst 将指定版本渲染为 PDF。 |
| 申请跟踪 | 网页界面或 `sync-status` | 记录申请事件、结果、复盘和薪酬信息；Gmail 只提出状态变更建议，不会静默修改。 |

## 主要功能

### 职位看板

- **Triage** (`/triage`)：处理尚未筛选或已拒绝的职位。
- **Shortlist** (`/shortlist`)：查看评分结果并决定是否批准定制。
- **Pipeline** (`/pipeline`)：查看已批准、定制和渲染中的职位。
- Triage、Shortlist 和 Pipeline 都可以把当前筛选条件保存为命名视图。

### 事实锁定资料与申请材料

- 从简历、补充材料和可选的 GitHub 项目构建 `data/profile/facts.json`。
- 定制简历中的项目、经历和技能必须携带可验证的来源标识。
- 事实检查和确定性来源门禁会阻止不受支持的陈述。
- 简历和求职信都可以保留多个版本，并通过 Typst 渲染为 PDF。

### 职业辅导

- **Profile Coach** (`/coach`)：逐个发现资料中的证据缺口，只根据用户回答起草新事实。
- **Mock Interviews** (`/interview`)：针对具体职位进行模拟面试，并生成评分复盘。
- **Career Lab** (`/career-lab`)：一次调用一个经过校验的本地职业技能；输出始终是草稿，不能替用户申请、上传或发送内容。

```bash
uv run resume-agent career-lab "准备薪酬谈判要点" \
  --skill salary-negotiation-prep --offer-application-id 7
```

### 申请时间线与复盘

每个职位的 **Tracking** 页签可以记录提交申请、招聘人员初筛、在线测评、技术面试、系统设计、行为面试、终面、offer、拒绝、撤回和自定义事件。事件可以包含时间、时区、形式、面试官、结果、笔记、复盘和薪酬明细。

**Applications** 页面 (`/applications`) 使用统一的数据集展示所有申请，支持搜索、排序、重复技术轮次展示，以及两种 CSV 导出：

- 宽表：便于人工阅读和横向比较。
- 事件明细表：无损保留每一个申请事件。

**Analytics** 页面 (`/analytics`) 使用同一份数据计算阶段流转、周期时间、当前申请时间线和 offer 对比。单个事件或全部即将发生的事件也可以下载为 `.ics` 日历文件。

### 公司研究与 H-1B 证据

职位详情中的 **Research** 页签将两类证据明确分开：

- **Company intelligence**：用户主动触发的公司研究，覆盖战略、近期动态、工程文化、挑战和竞争位置。只有研究结果中真实出现的来源 URL 和引用才能通过校验；刷新失败时保留上一份有效资料，过期内容会标记为陈旧但不会自动刷新。
- **Sponsorship**：可选的历史 H-1B 申报数据。历史申报不能证明当前职位提供赞助，也不会自动拒绝职位。

启用 H-1B MCP 集成时，只允许三个只读工具：`h1b_get_company_stats`、`h1b_search_h1b_jobs` 和 `h1b_get_available_data`。详细配置见 [环境变量参考](docs/configuration.md)。

### 运行历史和仪表盘

- 通知菜单持久保存后台任务的成功、失败和取消结果；即使浏览器断线，终态也不会丢失。
- Dashboard 展示工作队列、模拟面试分数趋势和职位来源故障。
- 长任务仍可通过 Server-Sent Events 实时显示进度，持久运行历史负责最终一致性。

---

## 前置要求

选择容器或原生安装方式：

- **容器运行**：Docker Engine 和 Docker Compose 插件。
- **原生开发**：[uv](https://docs.astral.sh/uv/) 与 Node.js 22+（含 npm）。项目使用 Python 3.13+。
- AI 功能需要至少一个模型提供商密钥。默认模型使用 Anthropic，也支持 OpenAI、Google Gemini 和 DeepSeek。

可选集成：

- GitHub token：提高仓库资料获取的速率限制。
- LinkedIn 专用账号：仅用于 `scrape`。
- Adzuna 等职位来源凭据：用于对应连接器。
- Gmail OAuth：用于状态同步、提醒和邮件草稿。

## 使用 Docker 启动

最简单的启动方式：

```bash
docker compose up --build
```

容器会把已构建的网页和 API 一起提供在 `http://localhost:8000`。Docker 镜像默认关闭浏览器型连接器；需要 LinkedIn 或其他浏览器来源时，请使用原生运行方式。

也可以直接构建并运行镜像：

```bash
docker build -t resume-agent .
docker run --name resume-agent --init --restart unless-stopped \
  -e APP_MODE=local \
  -p 127.0.0.1:8000:8000 \
  -v resume-agent-data:/app/data \
  resume-agent
```

如需在启动时注入模型密钥，请在创建 `.env` 后添加 `--env-file .env`。

生产部署见 [Railway 部署说明](docs/deploy-railway.md)。

## 原生安装

```bash
uv run --no-project scripts/bootstrap.py
uv run resume-agent setup
uv run python scripts/dev.py
```

第一条命令会以幂等方式安装锁定的 Python 和前端依赖；只有需要浏览器型职位来源时才传入 `--browser`。`resume-agent setup` 会引导配置密钥、搜索条件和职位连接器，并写入 `.env` 与 `config/*.yaml`。也可以从仓库中的 `.example` 文件手动创建配置。

启动 API 和网页前端：

开发脚本会同时启动 API 和 Vite，默认网页地址为 `http://localhost:5173`。如果已安装 `make`，也可以使用 `make setup` 和 `make dev`。

---

## 快速开始

```bash
# 1. 根据简历和可选 GitHub 来源构建事实锁定资料
uv run resume-agent profile build

# 2. 导入职位（三选一）
uv run resume-agent pull --limit 10
uv run resume-agent scrape --limit 10
uv run resume-agent addjob --company "Acme" --title "Backend Engineer" --jd-file jd.txt

# 3. 提取要求、筛选并评分
uv run resume-agent discover
uv run resume-agent match-gap

# 4. 在网页 Shortlist 页面中批准职位
make dev

# 5. 定制所有已批准的职位并生成求职信
uv run resume-agent tailor --approved
uv run resume-agent cover-letter --approved

# 6. 将指定简历版本渲染为 PDF
uv run resume-agent render 12

# 7. 在网页 Tracking 页签中记录申请事件

# 8. 可选：读取 Gmail 并提出状态变更建议
uv run resume-agent sync-status
uv run resume-agent sync-status --apply
```

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `resume-agent setup` | 交互式创建本地配置。 |
| `resume-agent profile build` | 从配置的来源构建事实锁定资料。 |
| `resume-agent addjob` | 手动添加一个职位。 |
| `resume-agent pull` | 运行所有已启用的职位连接器。 |
| `resume-agent scrape` | 使用本地浏览器获取 LinkedIn 职位。 |
| `resume-agent sources` | 查看职位来源和连接器运行历史。 |
| `resume-agent discover` | 提取职位要求、应用筛选条件并评分。 |
| `resume-agent match-gap` | 查看目标职位需要但资料中缺乏证据的技能。 |
| `resume-agent approve JOB_ID` | 从命令行批准职位。 |
| `resume-agent tailor` | 生成并评审事实锁定简历。 |
| `resume-agent cover-letter` | 生成经过来源校验的求职信。 |
| `resume-agent render VERSION_ID` | 将简历版本渲染为 PDF。 |
| `resume-agent sync-status` | 从 Gmail 生成申请状态建议。 |
| `resume-agent career-lab` | 使用一个已校验的职业技能创建草稿。 |
| `resume-agent serve` | 启动 API 和已构建的网页应用。 |

完整参数与示例见 [英文命令参考](README.md#command-reference)。

---

## 多用户托管模式

`resume-agent serve` 默认是无需登录的本地应用，只绑定回环地址。要公开服务或启用多用户模式，请设置管理员凭据并显式启动 hosted 模式：

```bash
uv run resume-agent serve --mode hosted --host 0.0.0.0 --port 8080
```

```env
AUTH_USERNAME=owner
AUTH_PASSWORD_HASH=<uv run resume-agent hash-password 的输出>
SESSION_SECRET=<足够长的随机值>
APP_BASE_URL=https://your-domain.example
```

每个用户都有独立的数据库、资料库、配置、密钥、输出文件和运行历史。管理员可以管理注册模式、邀请、模型费率、美元成本额度、积分、活跃职位上限和并发任务上限。

生产环境还应配置 `ALLOWED_HOSTS`、安全 Cookie、API 文档开关和持久化卷。完整要求见：

- [Railway 部署说明](docs/deploy-railway.md)
- [成本额度说明](docs/cost-quotas.md)
- [环境变量参考](docs/configuration.md)

## Gmail 配置

Gmail 集成只会读取邮件和创建草稿，不会发送邮件。

- **本地 CLI**：在 Google Cloud 创建 Desktop app OAuth 客户端，将下载的 JSON 保存为 `config/gmail_credentials.json`。
- **网页/API**：创建 Web application OAuth 客户端，将回调地址设置为 `<域名>/api/gmail/callback`，并配置 `GOOGLE_OAUTH_CLIENT_ID` 与 `GOOGLE_OAUTH_CLIENT_SECRET`。
- 在网页 **Settings → Keys** 中连接 Gmail。token 按工作区独立保存。

如果 OAuth 同意屏幕仍处于 Testing 状态，需要在 Google Cloud 中把每一个测试邮箱加入允许列表。

---

## API

```bash
uv run resume-agent serve
uv run resume-agent serve --mode hosted --host 0.0.0.0 --port 8080
```

- 本地交互式文档：`/docs`
- OpenAPI：`/openapi.json`
- 已提交的契约：`contracts/openapi.json`
- TypeScript 客户端：`contracts/ts/api.ts`
- 后台任务进度：`GET /api/runs/{id}` 和 `GET /api/runs/{id}/events`
- 持久运行终态：`GET /api/run-completions`
- 申请事件：`/api/jobs/{job_id}/events`
- 跨职位申请表：`/api/applications`
- 命名看板视图：`/api/board-views`
- 公司研究刷新：`POST /api/jobs/{job_id}/company-intelligence/refreshes`

API schema 发生变化后，运行 `bash scripts/gen_ts_client.sh` 更新前端客户端。

## 配置

复制 `.env.example` 为 `.env`。环境变量用于密钥、模型、认证、配额和外部集成；YAML 文件用于搜索、连接器、评审和渲染策略。

| 文件 | 作用 |
| --- | --- |
| `.env` | 模型密钥、服务模式、认证、Gmail 和外部集成。 |
| `config/search.yaml` | 地点、关键词、排除条件和其他搜索偏好。 |
| `config/connectors.yaml` | 职位来源、招聘网站和每个来源的限制。 |
| `config/profile_sources.yaml` | 简历、补充材料和 GitHub 资料来源。 |
| `config/review.yaml` | 默认快速评审流程。 |
| `config/review_deep.yaml` | 更完整的深度评审流程。 |
| `config/render.yaml` | Typst 模板和渲染设置。 |

模型 ID 使用提供商前缀：

```env
CHEAP_MODEL=gemini:gemini-3.5-flash-lite
MID_MODEL=deepseek:deepseek-v4-flash
PREMIUM_MODEL=claude-opus-5
```

裸模型 ID 使用 Anthropic；`openai:`、`gemini:` 和 `deepseek:` 分别路由到对应提供商。只需要配置实际使用的提供商密钥。

完整变量、边界和部署默认值见 [环境变量参考](docs/configuration.md)。

## 数据位置

| 路径 | 内容 |
| --- | --- |
| `data/resume_agent.db` | 本地模式下的职位、简历版本、求职信和申请记录。 |
| `data/profile/facts.json` | 事实锁定资料。 |
| `data/connector_runs.json` | 连接器运行历史。 |
| `data/gmail_token.json` | 本地 CLI 使用的 Gmail OAuth token。 |
| `output/` | 渲染后的简历和求职信 PDF。 |
| `.linkedin_profile/` | 本地 LinkedIn 浏览器会话。 |
| `templates/` | Typst 简历与求职信模板。 |

托管模式下，每个用户的数据位于独立工作区中。工作区导出和平台级数据根导出属于敏感资料，因为其中可能包含运行所需的密钥。

## 负责任地使用抓取功能

`scrape` 只适合个人、低频使用。请使用专用 LinkedIn 账号，保持较小的 `--limit`，并遵守目标网站的条款和适用法律。若不希望运行浏览器自动化，可以始终使用 `addjob` 或 URL 导入。

## 开发

```bash
uv run pytest
uv run pytest -k scraper
uv run ruff check .

cd web
npm run test:run
npm run lint
npm run build
```

后端测试使用假的智能体、浏览器和固定响应数据，正常情况下不需要模型密钥或网络访问。提交 API 契约变更时还应检查生成的 OpenAPI 和 TypeScript 客户端是否同步。

## 参与贡献

欢迎贡献。请阅读 [贡献指南](.github/CONTRIBUTING.md)，从 `main` 创建分支，并在提交 Pull Request 前运行相关测试和 `make verify`。

## 安全

请根据 [安全策略](.github/SECURITY.md) 私下报告漏洞，不要创建公开 issue。

仓库还包含以下安全文档：

- [威胁模型](docs/resume-agent-threat-model.md)
- [安全最佳实践报告](docs/security_best_practices_report.md)
- [ADR-0008：出口网关、租户存储和规范来源](docs/adr/0008-egress-gateway-tenant-storage-canonical-origin.md)

## 许可证

[MIT](LICENSE) © awbjcj
