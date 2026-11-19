# E-commerce Order API

一个基于 FastAPI 的异步电商订单后端示例项目，覆盖用户认证、商品与 SKU、订单创建、库存锁定、模拟支付、订单查询缓存以及超时自动关单等完整流程。

项目重点展示以下后端能力：

- FastAPI + Pydantic v2 的异步 API 设计
- SQLAlchemy 2.x AsyncSession + PostgreSQL
- Redis Cache-Aside 缓存
- Redis 幂等控制与支付回调并发控制
- Celery 延迟任务与异步通知
- 原子库存扣减、支付确认和库存释放
- Docker Compose 多服务编排
- Windows 环境下的 Celery Worker 运行方式

## 技术栈

| 组件 | 版本/说明 |
| --- | --- |
| Python | 3.11 - 3.13 |
| Web 框架 | FastAPI |
| 数据校验 | Pydantic v2 / pydantic-settings |
| ORM | SQLAlchemy 2.x Async ORM |
| 数据库驱动 | asyncpg |
| 数据库 | PostgreSQL 16 |
| 缓存与消息 | Redis 7 |
| 异步任务 | Celery 5.5+ |
| 数据库迁移 | Alembic |
| 认证 | JWT（PyJWT）+ bcrypt（passlib） |
| 开发工具 | pytest、pytest-asyncio、ruff |
| 容器编排 | Docker Compose |

## 核心功能

### 用户与权限

- 用户注册、登录和当前用户信息查询。
- JWT Bearer Token 认证。
- 角色分为 `ADMIN` 和 `CUSTOMER`。
- 普通用户只能查看或取消自己的订单；管理员可以访问所有订单。
- 商品创建仅允许管理员操作。

### 商品与库存

- 一个商品可包含多个 SKU。
- SKU 保存价格、可用库存 `available_stock` 和锁定库存 `locked_stock`。
- 下单时原子扣减可用库存并增加锁定库存。
- 支付成功时消费锁定库存。
- 取消订单时释放锁定库存并恢复可用库存。

### 订单

- 使用业务订单号 `order_no` 查询订单。
- 创建订单支持 `X-Idempotency-Key`，幂等记录保存在 Redis 中，默认有效期 24 小时。
- 订单、订单明细和状态流水在同一数据库事务中写入。
- 订单详情采用 Redis Cache-Aside 缓存。
- 订单创建成功后自动投递 Celery 超时取消任务。
- 支付和取消成功后删除订单详情缓存，不直接更新缓存。

### 支付与异步任务

- 提供模拟支付回调接口，只接受 `SUCCESS` 状态。
- 支付回调使用 Redis 锁避免同一订单重复处理。
- 支付成功后异步投递通知任务。
- 未支付订单超过配置时间后由 Celery Worker 自动取消并释放库存。

### 服务健康检查

- `GET /api/v1/health` 同时检查 PostgreSQL 和 Redis 连接。

## 系统架构

```text
Client / Swagger UI
        |
        v
   FastAPI API ---------------------> PostgreSQL
        |                                  ^
        |                                  |
        +----> Redis DB 0                  |
        |      - 订单详情缓存               |
        |      - 下单幂等键                 |
        |      - 支付回调锁                 |
        |                                  |
        +----> Redis DB 1 (Broker)         |
               Redis DB 2 (Result)         |
                    |                      |
                    v                      |
              Celery Worker ---------------+
                    |
                    +----> Redis DB 0：失效订单缓存
```

Redis 逻辑库在默认配置中的用途：

- `redis://localhost:6379/0`：业务缓存、幂等键、支付回调锁。
- `redis://localhost:6379/1`：Celery Broker。
- `redis://localhost:6379/2`：Celery Result Backend。

## 订单状态

| 状态 | 说明 |
| --- | --- |
| `PENDING_PAYMENT` | 待支付，下单后的初始状态 |
| `PAID` | 已支付 |
| `SHIPPED` | 已发货，当前仅定义状态，未提供接口 |
| `COMPLETED` | 已完成，当前仅定义状态，未提供接口 |
| `CANCELLED` | 已取消，库存已释放 |

当前实现的业务流转：

```text
PENDING_PAYMENT --支付回调成功--> PAID
PENDING_PAYMENT --手动取消/超时任务--> CANCELLED
```

## 主要业务流程

### 创建订单

1. API 校验请求与 `X-Idempotency-Key`。
2. 在 Redis 中预占幂等键。
3. 查询有效 SKU 和商品状态，服务端计算价格与小计。
4. 使用条件 UPDATE 原子扣减库存。
5. 写入订单、订单明细和初始状态流水。
6. 提交数据库事务。
7. 投递 Celery 超时取消任务。
8. 返回订单详情。

### 支付订单

1. 校验支付回调状态为 `SUCCESS`。
2. 使用 Redis 锁防止重复处理。
3. 条件更新订单状态为 `PAID`。
4. 消费锁定库存并写入状态流水。
5. 提交数据库事务。
6. 删除 `order:detail:{order_no}` 缓存。
7. 投递支付成功通知任务。

### 取消订单

1. 校验当前用户是否有操作权限。
2. 仅允许将 `PENDING_PAYMENT` 更新为 `CANCELLED`。
3. 释放每个 SKU 的锁定库存。
4. 写状态流水并提交事务。
5. 删除订单详情缓存。

### 超时自动取消

1. 下单接口调用 `cancel_unpaid_order_task.apply_async()`。
2. 延迟时间由 `ORDER_TIMEOUT_SECONDS` 控制，默认 1800 秒。
3. Worker 执行任务时重新查询数据库中的最新订单状态。
4. 状态仍为 `PENDING_PAYMENT` 时调用现有 `cancel_order()` 服务。
5. 已支付、已取消或不存在时直接跳过。
6. 任务内使用独立数据库引擎和 AsyncSession，不复用 FastAPI 请求会话。

## 项目结构

```text
e-commerce_project/
├── app/
│   ├── api/
│   │   ├── deps.py              # 数据库、Redis、认证依赖
│   │   └── v1/
│   │       ├── auth.py          # 注册、登录、当前用户
│   │       ├── orders.py        # 订单创建、查询、取消
│   │       ├── payments.py      # 模拟支付回调
│   │       ├── products.py      # 商品与 SKU
│   │       └── router.py        # v1 路由聚合、健康检查
│   ├── core/
│   │   ├── config.py            # 环境变量配置
│   │   └── security.py          # JWT 与密码哈希
│   ├── db/
│   │   ├── base.py              # SQLAlchemy Base
│   │   └── session.py           # 异步引擎与会话工厂
│   ├── models/                  # ORM 模型
│   ├── schemas/                 # Pydantic 请求与响应模型
│   ├── services/
│   │   ├── order.py             # 订单事务、幂等、状态流转
│   │   └── stock.py             # 原子库存操作
│   ├── tasks/
│   │   ├── celery_app.py        # Celery 应用配置
│   │   ├── notify.py            # 支付成功通知任务
│   │   └── order_timeout.py     # 超时自动取消任务
│   ├── utils/
│   │   └── cache.py             # JSON 缓存工具
│   └── main.py                  # FastAPI 应用入口
├── alembic/                     # 数据库迁移
├── tests/                       # pytest 测试目录
├── .env.example                 # 环境变量示例
├── docker-compose.yml           # api、worker、postgres、redis
├── Dockerfile
├── alembic.ini
├── pyproject.toml
└── requirements*.txt
```

## API 一览

基础前缀：`/api/v1`

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| `POST` | `/register` | 无 | 注册普通用户 |
| `POST` | `/login` | 无 | 使用表单登录并获取 JWT |
| `GET` | `/me` | Bearer | 查询当前用户 |
| `POST` | `/products/` | Bearer + ADMIN | 创建商品和 SKU |
| `GET` | `/products/` | 无 | 分页查询商品 |
| `GET` | `/products/{product_id}` | 无 | 查询商品详情 |
| `POST` | `/orders/` | Bearer | 创建订单，需 `X-Idempotency-Key` |
| `GET` | `/orders/{order_no}` | Bearer | 查询订单，仅本人或管理员 |
| `DELETE` | `/orders/{order_no}` | Bearer | 取消待支付订单 |
| `POST` | `/payments/callback` | 无 | 模拟支付成功回调 |
| `GET` | `/health` | 无 | 检查数据库与 Redis |

启动服务后可访问：

- Swagger UI：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`
- OpenAPI JSON：`http://localhost:8000/openapi.json`

## 快速启动：Docker Compose

### 1. 准备环境变量

```powershell
Copy-Item .env.example .env
```

至少修改：

```env
JWT_SECRET_KEY=请替换为至少32个字符的随机字符串
```

开发环境请勿将真实 `.env` 提交到版本库。

### 2. 构建镜像

`api` 和 `worker` 使用同一个镜像标签 `ecommerce-order-api:latest`。只构建一次即可：

```powershell
docker compose build api
```

### 3. 启动所有服务

```powershell
docker compose up -d
```

该命令会启动：

- `api`
- `worker`
- `postgres`
- `redis`

`worker` 会等待 PostgreSQL 和 Redis 健康后启动。

### 4. 执行数据库迁移

容器不会自动执行迁移，需要手动运行：

```powershell
docker compose exec api alembic upgrade head
```

### 5. 检查服务状态

```powershell
docker compose ps
docker compose logs -f api worker
```

API 健康检查：

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
```

预期结果：

```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok"
}
```

### Docker 下查看 Celery Broker 连接

```powershell
docker compose logs -f --tail=100 worker
```

启动日志中应包含：

```text
transport: redis://redis:6379/1
results: redis://redis:6379/2
celery@... ready.
```

可以进一步检查 Worker：

```powershell
docker compose exec worker celery -A app.tasks.celery_app:celery_app inspect ping
```

## 本地开发

### 1. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

### 2. 准备环境变量

```powershell
Copy-Item .env.example .env
```

本地运行时，`DATABASE_URL` 和 `REDIS_URL` 应指向本机可访问的地址。

### 3. 启动基础设施

如果使用 Docker 只启动 PostgreSQL 和 Redis：

```powershell
docker compose up -d postgres redis
```

### 4. 执行迁移

```powershell
alembic upgrade head
```

### 5. 启动 API

```powershell
uvicorn app.main:app --reload
```

### 6. 启动 Celery Worker

Windows 下必须使用 `solo` 池，不能使用 Celery 默认的 `prefork`：

```powershell
celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

Worker 需要在项目根目录启动，以便读取 `.env`。

## 环境变量

配置由 `pydantic-settings` 从 `.env` 加载。

### 应用

| 变量 | 示例值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `E-commerce Order API` | 应用名称 |
| `APP_VERSION` | `0.1.0` | 应用版本 |
| `APP_ENV` | `development` | `development`、`test`、`production` |
| `APP_DEBUG` | `true` | FastAPI 调试模式 |
| `API_V1_PREFIX` | `/api/v1` | API 前缀 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON 数组格式的跨域来源 |

### PostgreSQL

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ecommerce` | 必须是 asyncpg URL |
| `DB_POOL_SIZE` | `10` | 连接池大小 |
| `DB_MAX_OVERFLOW` | `20` | 连接池溢出上限 |
| `DB_POOL_RECYCLE` | `1800` | 连接回收秒数 |
| `DB_ECHO` | `false` | 是否输出 SQL 日志 |

### Redis

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | 业务缓存与幂等使用 DB 0 |
| `REDIS_MAX_CONNECTIONS` | `50` | Redis 连接池大小 |
| `ORDER_CACHE_TTL` | `600` | 订单详情缓存 TTL，单位秒 |

### Celery

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery Broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery 结果后端 |
| `ORDER_TIMEOUT_SECONDS` | `1800` | 未支付订单自动取消等待时间 |

### 安全

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `JWT_SECRET_KEY` | 示例占位符 | 至少 32 个字符，生产环境必须替换 |
| `JWT_ALGORITHM` | `HS256` | 支持 HS256、HS384、HS512 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access Token 有效期 |

### Docker Compose

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POSTGRES_USER` | `postgres` | PostgreSQL 用户 |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL 密码 |
| `POSTGRES_DB` | `ecommerce` | 数据库名称 |
| `POSTGRES_PORT` | `5432` | 宿主机端口 |
| `API_PORT` | `8000` | API 宿主机端口 |
| `REDIS_PORT` | `6379` | Redis 宿主机端口 |

## API 请求示例

### 注册用户

```http
POST /api/v1/register
Content-Type: application/json
```

```json
{
  "username": "demo",
  "password": "password123",
  "email": "demo@example.com"
}
```

### 登录并获取 Token

```http
POST /api/v1/login
Content-Type: application/x-www-form-urlencoded

username=demo&password=password123
```

返回：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

在 Swagger UI 中点击 `Authorize`，填入 Token 后即可访问受保护接口。

### 创建管理员并创建商品

项目未提供管理员初始化接口。开发环境可以直接在数据库中提升角色：

```powershell
docker compose exec postgres psql -U postgres -d ecommerce -c "UPDATE users SET role='ADMIN' WHERE username='demo';"
```

创建商品：

```json
{
  "name": "示例商品",
  "description": "用于订单流程测试",
  "is_active": true,
  "skus": [
    {
      "sku_code": "SKU-DEMO-001",
      "price": "99.90",
      "available_stock": 100
    }
  ]
}
```

### 创建订单

请求头必须包含幂等键：

```text
X-Idempotency-Key: order-test-001
```

请求体：

```json
{
  "items": [
    {
      "sku_id": 1,
      "quantity": 2
    }
  ]
}
```

重复提交相同的 `X-Idempotency-Key` 会返回原订单，不会重复扣减库存。

### 查询订单

```http
GET /api/v1/orders/{order_no}
Authorization: Bearer <access_token>
```

首次请求为缓存未命中，会查询 PostgreSQL 并回填 Redis。再次请求会命中缓存。

### 取消订单

```http
DELETE /api/v1/orders/{order_no}
Authorization: Bearer <access_token>
```

### 模拟支付成功

```http
POST /api/v1/payments/callback
Content-Type: application/json
```

```json
{
  "order_no": "ORD20260101000000000000ABCD1234",
  "status": "SUCCESS"
}
```

## Redis 缓存设计

订单详情缓存键：

```text
order:detail:{order_no}
```

缓存策略为 Cache-Aside：

1. 读取时先查 Redis。
2. 命中后将 JSON 反序列化为 `OrderOut`。
3. 未命中时查询数据库并写入 Redis。
4. 支付或取消事务提交成功后删除缓存。

缓存 TTL 通过 `ORDER_CACHE_TTL` 配置，默认 600 秒。

删除缓存而不是更新缓存的原因：

- 并发写入时，多个请求更新缓存的顺序无法保证，旧状态可能覆盖新状态。
- 删除后由下一次读取从数据库回填，更容易保证缓存最终与数据库一致。
- 先提交数据库事务，再删除缓存，避免其他请求在事务提交前把旧数据重新写回缓存。
- 如果 Redis 删除失败，TTL 会限制旧缓存的最长存活时间。

## Celery 任务设计

### 超时自动取消

任务名称：

```text
app.tasks.order_timeout.cancel_unpaid_order_task
```

下单成功后调用：

```python
cancel_unpaid_order_task.apply_async(
    args=[order_no],
    countdown=settings.order_timeout_seconds,
)
```

任务内部特点：

- 使用 `asyncio.run()` 执行异步逻辑。
- 每次任务创建独立的 SQLAlchemy 异步引擎和 AsyncSession。
- 使用 `NullPool`，避免 Windows 下不同事件循环复用旧连接。
- 重新查询最新订单状态，不信任下单时的状态快照。
- 与支付回调并发时，通过订单状态条件更新避免重复取消或重复释放库存。

### 支付成功通知

任务名称：

```text
app.tasks.notify.send_payment_success_notify
```

支付成功后投递，用于模拟发送通知。

### Windows 运行要求

Windows 下必须使用：

```powershell
celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

项目在 `celery_app.py` 中也针对 Windows 自动设置 `worker_pool=solo`。

### 10 秒测试超时关单

修改 `.env`：

```env
ORDER_TIMEOUT_SECONDS=10
```

重启 API 和 Worker：

```powershell
docker compose up -d --force-recreate api worker
```

本地进程方式则分别重启 `uvicorn` 和 Celery Worker。

然后创建订单并等待约 10 秒，观察：

- API 日志：`Scheduled timeout cancellation for order ... in 10 seconds`
- Worker 日志：`Order ... cancelled automatically after timeout`
- 订单状态变为 `CANCELLED`
- SKU 可用库存恢复
- Redis 中该订单详情缓存被删除

测试完成后建议恢复：

```env
ORDER_TIMEOUT_SECONDS=1800
```

## 数据库迁移

查看当前迁移版本：

```powershell
alembic current
```

升级到最新：

```powershell
alembic upgrade head
```

回退一个版本：

```powershell
alembic downgrade -1
```

创建新迁移：

```powershell
alembic revision --autogenerate -m "describe change"
```

当前迁移链：

```text
5603d6ca1980 -> c0e8eac523ed -> bbec2d24640f -> 8e03ba53a633
```

## 测试与代码检查

安装开发依赖：

```powershell
pip install -r requirements-dev.txt
```

运行测试：

```powershell
pytest
```

运行 Ruff：

```powershell
ruff check .
ruff format --check .
```

基础语法检查：

```powershell
python -m compileall -q app
```

当前 `tests/` 目录已配置为测试入口，可按业务继续补充单元测试和集成测试。

## 常见问题

### 订单没有自动取消

依次检查：

1. Celery Worker 是否正在运行。
2. Worker 日志中是否显示已连接 `redis://redis:6379/1` 或本地 Broker。
3. API 日志中是否出现 `Scheduled timeout cancellation`。
4. `.env` 中的 `ORDER_TIMEOUT_SECONDS` 是否生效。
5. 修改 `.env` 后是否重启了 API 和 Worker。
6. 订单是否已经变为 `PAID` 或 `CANCELLED`。

### Windows 下 Worker 无法启动

确认命令中包含：

```text
--pool=solo
```

不要使用默认的 `prefork` 进程池。

### 创建商品返回 403

商品创建需要管理员权限。先注册用户，再将数据库中的角色更新为 `ADMIN`。

### 下单返回 409

常见原因：

- 相同幂等键的请求仍在处理中。
- 库存不足。
- SKU 或商品不可用。
- 数据库唯一约束冲突。

### 修改代码后 Worker 仍是旧逻辑

挂载代码卷只能让容器读取宿主机文件。Celery Worker 不会自动重新加载已导入的任务模块，修改任务代码后需要重启：

```powershell
docker compose restart worker
```

### 修改 `.env` 后配置未生效

配置在进程启动时加载。需要重建或重启相关服务：

```powershell
docker compose up -d --force-recreate api worker
```

## 开发与生产注意事项

- 当前支付回调为开发模拟实现，没有校验第三方签名，不应直接用于生产。
- 管理员角色通过数据库手动提升，项目尚未提供后台管理接口。
- Docker Compose 中的 Redis 未配置密码，仅适合本地开发。
- Cache-Aside 提供最终一致性；在极端并发窗口下仍可能短时间读取旧缓存，TTL 是兜底保护。
- Worker 容器固定使用 `solo` 池，稳定性较高但并发能力有限；生产环境可根据平台和负载调整部署拓扑。
- 生产环境必须替换 `JWT_SECRET_KEY`，并启用 HTTPS、限流、审计和更严格的支付验签。

## License

当前仓库未包含开源许可证文件。使用前请根据实际项目归属补充许可证。
