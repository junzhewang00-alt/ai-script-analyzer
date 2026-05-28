# AI 短剧剧本分析器 (Flask 版)

基于 Flask 的全栈短剧剧本 AI 分析平台，支持 7 维度深度分析、提示词工坊、积分系统、Stripe/PayJS 双支付。

## 技术栈

| 层面 | 技术 |
|------|------|
| 框架 | Flask 3.x + Jinja2 模板 |
| 语言 | Python 3.14 |
| 数据库 | SQLite (Flask-SQLAlchemy + SQLAlchemy) |
| 认证 | Flask-Login (session based) |
| AI SDK | OpenAI Python SDK (兼容 DeepSeek/任意 OpenAI API) |
| 支付 | Stripe + PayJS (双渠道) |
| 生产部署 | Waitress (Windows) / Gunicorn (Linux) + Nginx 反向代理 |
| 限流 | 自研内存滑动窗口 `limiter.py` |

## 项目结构

```
ai-script-analyzer/
├── app.py              # 主应用: Flask 初始化、全部路由、任务管理、LLM 调用
├── auth.py             # 认证蓝图: 登录/注册/登出/签到
├── models.py           # 数据模型: User, CreditLog, RechargeOrder + 积分常量
├── limiter.py          # 内存滑动窗口限流器
├── pay_bp.py           # 支付蓝图: 充值/下单/回调/确认
├── payjs_pay.py        # PayJS 扫码支付 SDK 封装
├── stripe_pay.py       # Stripe PaymentIntent 封装
├── deploy.sh           # 云服务器一键部署脚本 (systemd + nginx)
├── update.sh           # git pull + 重启服务
├── DESIGN.md           # Google Stitch 9 章节设计系统
├── requirements.txt    # Python 依赖
├── .env                # 环境变量 (LLM + 支付密钥)
├── .env.example        # 环境变量模板
├── .jobs/              # 分析任务 JSON 持久化目录 (24h TTL)
├── analyzer/
│   ├── __init__.py
│   ├── llm.py          # OpenAI 客户端封装 (缓存 + 流式取消)
│   ├── prompts.py      # 7 维度系统提示词 + 概览提示词
│   └── parser.py       # 文件解析 (.txt .pdf .fdx .docx)
├── static/
│   ├── style.css       # 全局样式 (DESIGN.md 设计系统实现)
│   └── script.js       # 全局 JS (登录页视频背景、分析页交互等)
└── templates/
    ├── base.html       # 基础布局 (导航栏、用户信息、flash 消息)
    ├── index.html      # 首页: 剧本提交 (粘贴/上传)
    ├── manual.html     # 分析页: 7 维度卡片 + 概览 + 导出
    ├── prompts.html    # 提示词工坊: 标签库 + 翻译面板
    ├── dashboard.html  # 积分面板: KPIs + 趋势 + 日志
    ├── recharge.html   # 充值页: Stripe Elements + PayJS 二维码
    ├── login.html      # 登录页
    ├── register.html   # 注册页
    └── auth_base.html  # 认证页面布局 (视频背景)
```

## URL 路由

### 页面路由
| 路径 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页 (剧本提交) |
| `/prompts` | GET | 提示词工坊 |
| `/analyze` | POST | 提交剧本，创建分析任务 |
| `/analyze/<job_id>` | GET | 分析页 (手动触发维度) |
| `/dashboard` | GET | 积分面板 |
| `/auth/login` | GET/POST | 登录 |
| `/auth/register` | GET/POST | 注册 |
| `/auth/logout` | GET | 登出 |
| `/pay/recharge` | GET | 充值页面 |

### API 路由
| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/config` | GET/POST | 获取/保存 API 配置 (每 session) |
| `/api/job/<job_id>` | GET | 获取任务状态和结果 |
| `/api/job/<job_id>/run/<index>` | POST | 启动单个维度分析 (fire-and-forget) |
| `/api/job/<job_id>/cancel/<index>` | POST | 取消运行中的维度 |
| `/api/job/<job_id>/overview` | POST | 生成分析概览 |
| `/api/analyze` | POST | 一键全维度分析 (ThreadPool) |
| `/api/translate` | POST | 中文提示词翻译为英文 |
| `/api/dashboard/stats` | GET | 积分统计 (KPIs + 趋势 + 分布) |
| `/auth/signin` | POST | 每日签到 |
| `/pay/create` | POST | 创建充值订单 |
| `/pay/confirm` | POST | Stripe 前端确认支付 |
| `/pay/webhook` | POST | Stripe 异步回调 |
| `/pay/notify` | POST | PayJS 异步回调 |
| `/pay/status/<out_trade_no>` | GET | 查询支付状态 |

## 数据库 Schema

### User 表
| 列 | 类型 | 说明 |
|----|------|------|
| id | Integer PK | 自增 |
| email | String(120) UNIQUE | 登录邮箱 |
| password_hash | String(256) | werkzeug 哈希 |
| nickname | String(60) | 显示名称 |
| credits | Integer | 积分余额 (默认 200) |
| last_signin_date | Date | 签到日期 |
| is_admin | Boolean | 管理员标记 |
| created_at | DateTime | 注册时间 |

### CreditLog 表
| 列 | 类型 | 说明 |
|----|------|------|
| id | Integer PK | |
| user_id | FK→User | |
| type | String(30) | signup_bonus / daily_signin / consume / recharge |
| amount | Integer | 正=获得, 负=消耗 |
| balance_after | Integer | 变动后余额 |
| description | String(200) | |
| created_at | DateTime | |

### RechargeOrder 表
| 列 | 类型 | 说明 |
|----|------|------|
| id | Integer PK | |
| user_id | FK→User | |
| out_trade_no | String(32) UNIQUE | 商户订单号 |
| pay_channel | String(16) | stripe / payjs |
| payjs_order_id | String(32) | PayJS 返回的订单ID |
| amount_fen | Integer | 金额(分) |
| amount_yuan | Integer | 金额(元) |
| credits | Integer | 获得积分数 |
| body | String(64) | 商品描述 |
| status | String(16) | pending / paid / failed |
| payjs_raw | Text | 回调原始 JSON |
| created_at / paid_at | DateTime | |

## 积分系统

| 操作 | 消耗/获得 |
|------|-----------|
| 完整分析 ≤5000字 | -12 |
| 完整分析 ≤15000字 | -25 |
| 完整分析 ≤30000字 | -40 |
| 单维度分析 | -5 |
| 概览生成 | -5 |
| 翻译 | -2 |
| 注册赠送 | +200 |
| 每日签到 | +5 |

| 充值套餐 | 价格 | 积分 |
|----------|------|------|
| 基础包 | ¥10 | 100 |
| 进阶包 | ¥20 | 220 (+10%) |
| 专业包 | ¥50 | 600 (+20%) |
| 企业包 | ¥100 | 1300 (+30%) |

## 分析流程

1. 用户提交剧本 (POST `/analyze`) → 创建任务 (内存 + `.jobs/` JSON 持久化)
2. 重定向到 `/analyze/<job_id>` → 轮询 `GET /api/job/<job_id>` (1.5s)
3. 用户手动触发维度 `POST /api/job/<job_id>/run/<index>` → daemon 线程执行
4. 至少 3 个维度完成后可生成概览 `POST /api/job/<job_id>/overview`
5. 支持取消运行中的分析 → threading.Event 信号中断流式请求
6. 支持导出 MD/TXT

## 关键设计决策

- **任务存储**: 内存 `_jobs` dict + `.jobs/` JSON 文件持久化，24h TTL
- **LLM 调用**: daemon 线程 fire-and-forget，支持 AbortSignal (via threading.Event)
- **流式取消**: 在 OpenAI stream chunk 间检查 cancel_event，中断则关闭流
- **演示模式**: 未配置 LLM_API_KEY 时显示模拟结果
- **API 配置**: 用户可覆盖 LLM 配置，存于服务端 `_api_configs` dict (按 session.sid)
- **限流器**: 自研 `RateLimiter`，每个 key 独立滑动窗口 deque，5 分钟清理一次过期 key
- **支付原子化**: `_mark_paid_and_credit()` 使用 `with_for_update()` 行锁，防止重复到账
- **API 路由保护**: `before_request` 对未登录用户访问 `/api/` 和 `/pay/` 返回 404
- **样式**: 暗色主题，DESIGN.md 定义的 indigo 强调色 (`#818cf8`)，深炭色背景 (`#0b0b0f`)
- **一键分析 API**: `/api/analyze` 使用 `ThreadPoolExecutor` 并发执行所有维度

## 环境变量 (`.env`)

```bash
LLM_API_BASE=https://api.deepseek.com/v1   # LLM API 地址
LLM_API_KEY=sk-xxx                          # API 密钥
LLM_MODEL=deepseek-chat                     # 模型名
FLASK_SECRET_KEY=xxx                        # Flask session 密钥
PAYJS_MCHID=xxx                             # PayJS 商户号
PAYJS_KEY=xxx                               # PayJS 密钥
PAYJS_NOTIFY_URL=https://xxx/pay/notify     # PayJS 回调地址
STRIPE_SECRET_KEY=sk_test_xxx               # Stripe 密钥
STRIPE_PUBLISHABLE_KEY=pk_test_xxx          # Stripe 公钥
STRIPE_WEBHOOK_SECRET=whsec_xxx             # Stripe Webhook 密钥
```

## 运行

```bash
pip install -r requirements.txt
python app.py          # 开发模式 (http://127.0.0.1:5000, debug, threaded)
python app.py --prod   # 生产模式 (Waitress, http://0.0.0.0:5000)
```

## 部署

云服务器 `115.28.184.220`，通过 `deploy.sh` 一键部署：systemd 管理进程，Nginx 反向代理 (80→5000)。

```bash
./update.sh   # 从 GitHub 拉取更新并重启服务
```

GitHub: `https://github.com/junzhewang00-alt/ai-script-analyzer`

## 当前状态 (2026-05)

- ✅ 注册/登录 (Flask-Login, session 认证)
- ✅ 剧本提交 (粘贴/上传 .txt .pdf .fdx .docx)
- ✅ 7 维度 AI 分析 (人物/结构/对白/主题/综合评估/图片提示词/视频提示词)
- ✅ 概览汇总生成 (需至少 3 维度完成)
- ✅ 一键全维度 API (`/api/analyze`)
- ✅ 演示模式 (无 API 配置时)
- ✅ 积分系统 (消耗/签到/日志)
- ✅ 积分仪表盘 (KPIs/趋势/消费分布)
- ✅ 提示词工坊 (标签库 + 中译英)
- ✅ 分析结果导出 (MD/TXT)
- ✅ 限流保护 (自研 RateLimiter)
- ✅ Stripe 支付 (PaymentIntent + Webhook)
- ✅ PayJS 支付 (扫码支付 + 异步通知)
- ✅ 充值页面 (Stripe Elements + PayJS 二维码)
- ✅ 生产部署 (systemd + nginx + Waitress)
- ✅ 一键部署脚本

## Next.js 版关系

同一项目有 Next.js 重写版位于 `C:\Users\ZhuanZ\Desktop\ai-script-analyzer-next`，功能相似但架构不同。核心提示词和 7 维度分析逻辑保持一致。
