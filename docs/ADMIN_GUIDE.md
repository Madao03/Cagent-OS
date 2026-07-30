# CagentOS 管理员指南

> **版本**: Phase 4c+ (内测)
> **更新**: 2026-07-20
> **适用对象**: 服务部署者 / 内测管理员(你)

本指南涵盖内测阶段的全部管理操作:用户管理、邀请码、数据备份、环境配置、故障排查。

---

## 目录

1. [快速开始](#1-快速开始)
2. [环境变量配置](#2-环境变量配置)
3. [用户管理 CLI](#3-用户管理-cli)
4. [邀请码管理](#4-邀请码管理)
5. [Admin HTTP API](#5-admin-http-api)
6. [数据库位置与备份](#6-数据库位置与备份)
7. [多用户隔离原理](#7-多用户隔离原理)
8. [Memory 系统](#8-memory-系统)
9. [常见运维场景](#9-常见运维场景)
10. [故障排查](#10-故障排查)

---

## 1. 快速开始

### 首次启动

```powershell
# 1. 设置必需的环境变量(每次新开终端都要设)
$env:JWT_SECRET_KEY="your-random-secret-at-least-32-chars"
$env:ADMIN_TOKEN="your-admin-shared-secret"

# 2. 启动服务
cd d:\Projects\cagent-os
uvicorn cagent_os.interfaces.http.app:create_app --factory --port 8000 --host 127.0.0.1
```

### 生成第一批邀请码

```powershell
# 另开一个终端
python scripts/generate_invitation_codes.py --count 10 --note "首批内测"
```

输出 10 个 8 位邀请码,把它们发给内测用户。

### 验证服务健康

```powershell
curl http://127.0.0.1:8000/health
# {"status":"healthy"}
```

---

## 2. 环境变量配置

| 变量名 | 必需 | 用途 | 默认行为 |
|:------|:----:|:----|:--------|
| `JWT_SECRET_KEY` | ✅ 生产 | JWT 签名密钥(≥32 字符) | 不设 → 每次重启都让所有用户重新登录 |
| `ADMIN_TOKEN` | ✅ 生产 | Admin API 鉴权 | 不设 → `/api/v1/admin/*` 返回 503 |
| `PORT` | ❌ | HTTP 端口 | 默认 8000 |
| `HOST` | ❌ | 监听地址 | 默认 127.0.0.1(本机) |

### 生成强随机密钥

```powershell
# JWT_SECRET_KEY (用于 token 签名)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# ADMIN_TOKEN (用于 admin API)
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### 生产部署推荐

把环境变量写到 `.env` 文件(不要提交到 git):

```env
# .env
JWT_SECRET_KEY=你的-长随机字符串
ADMIN_TOKEN=你的-admin-token
```

---

## 3. 用户管理 CLI

所有用户管理操作都通过 `scripts/manage_users.py`:

### 列出所有用户

```powershell
# 全部用户(包括禁用的)
python scripts/manage_users.py list

# 只看活跃用户
python scripts/manage_users.py list --active
```

输出示例:
```
USERNAME                  STATUS     VIA          CREATED                INVITATION_CODE
----------------------------------------------------------------------------------------
alice                     active     invitation   2026-07-20T10:00:00    CNWA56TJ
bob                       active     invitation   2026-07-20T11:00:00    AEX5TJJN
spam_user                 DISABLED   invitation   2026-07-20T12:00:00    S5ZAWQMT

Total: 3 users (2 active, 1 disabled)
```

### 禁用用户

```powershell
python scripts/manage_users.py disable spam_user
# ✓ Disabled user: spam_user
```

禁用后:
- 该用户的 token 立即失效(下次请求 `/me` 返回 403)
- 该用户**无法重新登录**(login 返回 403)
- 已存的对话和 memory **不会被删除**(只是访问被拒)

### 启用用户

```powershell
python scripts/manage_users.py enable spam_user
# ✓ Enabled user: spam_user
```

---

## 4. 邀请码管理

### 生成邀请码

```powershell
# 生成 10 个
python scripts/generate_invitation_codes.py --count 10

# 带备注
python scripts/generate_invitation_codes.py --count 5 --note "发给小红书粉丝群"
```

输出示例:
```
Generated 5 invitation codes:
  CNWA56TJ
  AEX5TJJN
  S5ZAWQMT
  JX9Q9C52
  W7KSD9V7
```

### 查看邀请码使用情况

```powershell
# 通过 manage_users.py
python scripts/manage_users.py invitations

# 或通过 generate_invitation_codes.py
python scripts/generate_invitation_codes.py --list           # 所有码
python scripts/generate_invitation_codes.py --list-available # 只看未使用
```

输出示例:
```
CODE         STATUS     CREATED                USED_BY    NOTE
----------------------------------------------------------------------
CNWA56TJ     USED       2026-07-20T10:00:00    4797b0e1   首批内测
AEX5TJJN     available  2026-07-20T10:00:00    -          首批内测

Total: 19 codes (18 available, 1 used)
```

### 邀请码设计

- **格式**: 8 位字符,字母数字(无 `0/O/1/I/L` 避免混淆)
- **使用规则**: 一次性,注册时消费,**不可重复使用**
- **失败回滚**: 用户名重复时,邀请码**不会被消费**(原子性保证)
- **审计**: 每个码记录 `created_by`、`used_by`、`used_at`、`note`

### 通过 API 生成(可选)

```powershell
$env:ADMIN_TOKEN="your-admin-token"
$headers = @{ "X-Admin-Token" = $env:ADMIN_TOKEN; "Content-Type" = "application/json" }
$body = '{"count": 5, "note": "API 生成"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/admin/invitations/generate" -Method Post -Headers $headers -Body $body
```

---

## 5. Admin HTTP API

所有 `/api/v1/admin/*` 端点都需要 `X-Admin-Token` 请求头。

### 端点列表

| 方法 | 路径 | 用途 |
|:----|:----|:----|
| GET | `/api/v1/admin/users` | 列出所有用户 |
| POST | `/api/v1/admin/users/{username}/disable` | 禁用用户 |
| POST | `/api/v1/admin/users/{username}/enable` | 启用用户 |
| POST | `/api/v1/admin/invitations/generate` | 生成邀请码(参数:`{count, note}`) |
| GET | `/api/v1/auth/invitations` | 列出所有邀请码(无需 admin token,仅限内测) |

### 使用示例(PowerShell)

```powershell
$env:ADMIN_TOKEN="your-admin-token"
$headers = @{ "X-Admin-Token" = $env:ADMIN_TOKEN }

# 列出所有用户
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/admin/users" -Headers $headers

# 禁用用户
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/admin/users/spam_user/disable" -Method Post -Headers $headers

# 生成 5 个邀请码
$body = '{"count": 5, "note": "API 批量"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/admin/invitations/generate" -Method Post -Headers $headers -Body $body
```

### 安全注意

- **`ADMIN_TOKEN` 必须保密**——不要提交到 git、不要发到群里
- `/api/v1/auth/invitations` 是**无鉴权**的(内测便利),上线前需移除或加保护
- 建议在 Nginx 层把 `/api/v1/admin/*` 限制为只能从内网访问

---

## 6. 数据库位置与备份

### 数据库文件

```
data/
├── users.db                # 用户账号(username + PIN 哈希 + disabled 标记)
├── invitation_codes.db     # 邀请码(code + 使用状态)
├── conversations.db        # 对话历史(按 principal_id 隔离)
├── memory.db               # 用户记忆(agent_notes + user_profile + 结构化事实)
├── vectors/                # RAG 向量索引(numpy)
└── chroma/                 # (废弃,Phase 3 遗留)
```

### 备份

最简单的方式——直接拷贝整个 `data/` 目录:

```powershell
# 备份到带时间戳的目录
$backup = "data-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -Path data -Destination $backup -Recurse
Write-Host "Backup created: $backup"
```

或用 SQLite 的 `.backup` 命令做在线备份(服务运行时也能用):

```powershell
python -c "import sqlite3; c = sqlite3.connect('data/users.db'); c.backup(open('users.db.bak', 'wb')); print('users.db backed up')"
```

### 恢复

```powershell
# 1. 停服务
# 2. 覆盖 data/ 目录
Copy-Item -Path data-backup-20260720/* -Destination data/ -Recurse -Force
# 3. 重启服务
```

### 清空(开发/测试用)

```powershell
# 清空用户(保留邀请码)
python scripts/_reset_users_db.py

# 完全重置(谨慎!删所有用户、对话、memory)
Remove-Item data/*.db, data/*.db-wal, data/*.db-shm -ErrorAction SilentlyContinue
```

---

## 7. 多用户隔离原理

### 隔离矩阵

| 数据类型 | 隔离字段 | 隔离方式 | 跨用户访问 |
|:--------|:--------|:--------|:----------:|
| 用户账号 | `id` (UUID) | JWT token 里携带 `sub=user_id` | ❌ |
| 对话历史 | `principal_id` | `WHERE principal_id = ?` + ownership 校验 | ❌ 403 |
| Memory(agent_notes) | `user_id` | 表 PRIMARY KEY 是 `(user_id)` | ❌ |
| Memory(user_profile) | `user_id` | 同上 | ❌ |
| Memory(user_facts) | `user_id` | `WHERE user_id = ?` | ❌ |
| RAG 知识库 | (无) | **所有用户共享** | ✅ |

### 关键代码位置

- [auth_context.py](../src/cagent_os/interfaces/http/auth_context.py):从 JWT 解析 `principal_id`
- [routes_runs.py:47](../src/cagent_os/interfaces/http/routes_runs.py#L47):conversation 创建时 `user_id=principal_id`(memory 隔离修复)
- [routes_conversations.py:76](../src/cagent_os/interfaces/http/routes_conversations.py#L76):list_events 通过 ConversationService 做 ownership 校验

### 验证隔离

```powershell
# 用 alice 的 token 访问 bob 的对话 → 应返回 403
$alice_token = "..."
curl -H "Authorization: Bearer $alice_token" `
     http://127.0.0.1:8000/api/v1/conversations/bob-conv-id/events
# HTTP 403: Conversation belongs to another principal.
```

---

## 8. Memory 系统

### 架构(Hermes 风格双层)

每个用户有**两个 markdown 风格的记忆文件**:

| 文件 | 用途 | 容量上限 |
|:----|:----|:--------:|
| `agent_notes` | Agent 的笔记(用户偏好、项目上下文、环境事实) | 2000 字符 |
| `user_profile` | 用户档案(投资风格、沟通偏好) | 1500 字符 |

**外加结构化数据表**(保留兼容):
- `user_facts` (KV 事实)
- `investment_theses` (按 ticker 的投研观点)
- `contradiction_log` (矛盾检测)

### 关键设计

1. **LLM 自主写入** —— DeepSeek 通过工具调用 `memory.update_notes/profile` 自主决定记什么
2. **容量上限逼迫整理** —— 超限时返回 `current_body` + 整理提示,而不是报错
3. **每轮自动注入** —— `get_hot_memory_prompt()` 把两文件内容拼到 system prompt
4. **用户隔离** —— 每个用户独立的 agent_notes 和 user_profile

### 查看某用户的 memory

```powershell
# 拿到该用户的 token(让用户提供,或 admin 模拟登录)
$token = "..."

# 查看完整 memory 状态
curl -H "Authorization: Bearer $token" `
     http://127.0.0.1:8000/api/v1/memory/full_state
```

### 手动编辑 memory

```powershell
# 整体替换 agent_notes
$body = '{"body": "# Agent Notes\n\n- 用户偏好中文\n- 关注半导体"}'
curl -X PUT -H "Authorization: Bearer $token" `
     -H "Content-Type: application/json" `
     -d $body `
     http://127.0.0.1:8000/api/v1/memory/agent_notes
```

---

## 9. 常见运维场景

### 场景 1:新内测用户加入

1. 管理员生成邀请码:
   ```powershell
   python scripts/generate_invitation_codes.py --count 1 --note "给小明"
   ```
2. 把邀请码 + 用户注册指引发给用户:
   > 访问 http://your-server/,点「注册」,输入:
   > - 邀请码:`CNWA56TJ`
   > - 用户名:自选(3-30 位)
   > - PIN 码:自选(4-6 位数字)

### 场景 2:用户忘记 PIN

当前**没有自动重置流程**(无 SMTP)。两种处理方式:

**方式 A:管理员手动改 PIN(推荐)**
```powershell
# 目前没有 CLI 命令,需写 SQL(谨慎)
python -c @"
import sqlite3, bcrypt
c = sqlite3.connect('data/users.db')
pin_hash = bcrypt.hashpw(b'1234', bcrypt.gensalt()).decode()
c.execute('UPDATE users SET pin_hash=? WHERE username=?', (pin_hash, '忘记密码的用户名'))
c.commit(); c.close()
print('PIN reset to 1234')
"@
```
然后告诉用户新 PIN,让用户登录后自己改。

**方式 B(未来):** 加 `POST /api/v1/auth/reset_pin` 端点 + 管理员审批流程。

### 场景 3:用户反馈"看不到自己历史对话"

排查步骤:
1. 让用户提供 username,管理员查用户状态:
   ```powershell
   python scripts/manage_users.py list | findstr username
   ```
2. 如果是 DISABLED → 启用他:
   ```powershell
   python scripts/manage_users.py enable username
   ```
3. 如果状态正常 → 让用户:
   - 清浏览器 localStorage(可能 token 过期)
   - 重新登录
   - 看 sidebar 历史会话列表

### 场景 4:服务迁移到新机器

```powershell
# 1. 在老机器上备份
Compress-Archive -Path data -DestinationPath cagentos-data.zip

# 2. 拷贝到新机器并解压
Expand-Archive -Path cagentos-data.zip -DestinationPath .

# 3. 设置环境变量(关键!)
$env:JWT_SECRET_KEY="<和老机器相同,否则所有 token 失效>"
$env:ADMIN_TOKEN="<可选,换新的也行>"

# 4. 启动服务
uvicorn cagent_os.interfaces.http.app:create_app --factory --port 8000
```

### 场景 5:清理测试数据准备上线

```powershell
# 1. 备份当前数据
Compress-Archive -Path data -DestinationPath "data-pre-cleanup-$(Get-Date -Format yyyyMMdd).zip"

# 2. 清空所有用户数据(保留 RAG 知识库)
Remove-Item data\users.db, data\users.db-* -ErrorAction SilentlyContinue
Remove-Item data\invitation_codes.db, data\invitation_codes.db-* -ErrorAction SilentlyContinue
Remove-Item data\conversations.db, data\conversations.db-* -ErrorAction SilentlyContinue
Remove-Item data\memory.db, data\memory.db-* -ErrorAction SilentlyContinue

# 3. 重新生成干净邀请码
python scripts/generate_invitation_codes.py --count 5 --note "上线首批"
```

---

## 10. 故障排查

### 问题:启动报 `ADMIN_TOKEN` 相关错误

**原因**: `routes_auth.py` 检查 `ADMIN_TOKEN` 环境变量。
**解决**: 启动前 `$env:ADMIN_TOKEN="任意字符串"` 即可。

### 问题:所有用户重启后都需要重新登录

**原因**: `JWT_SECRET_KEY` 未设置,每次 uvicorn 重启都生成新的随机密钥。
**解决**:
```powershell
$env:JWT_SECRET_KEY="固定的一串字符至少32位"
```

### 问题:用户登录返回 403 "Account has been disabled"

**原因**: 该用户被管理员禁用了。
**解决**:
```powershell
python scripts/manage_users.py enable username
```

### 问题:用户注册返回 403 "Invitation code has already been used"

**原因**: 邀请码一次性,已被别人用过。
**解决**: 给用户发个新邀请码。

### 问题:用户注册返回 409 "Username is already taken"

**原因**: 用户名已被占用。
**解决**: 让用户换个用户名。

### 问题:`/api/v1/admin/users` 返回 503

**原因**: 服务端没设 `ADMIN_TOKEN` 环境变量。
**解决**: 见 [2. 环境变量配置](#2-环境变量配置)。

### 问题:LLM 在对话中"失忆"(不记得之前说过的)

**原因 可能**:
1. 用户的 memory 是空的(第一次对话) → 正常
2. 服务重启了 + 没设 `JWT_SECRET_KEY` → token 失效,用户被当成新会话
3. Memory 工具未被调用 → LLM 判断不需要记忆

**诊断**:
```powershell
# 查看用户的 memory
curl -H "Authorization: Bearer $user_token" http://127.0.0.1:8000/api/v1/memory/full_state
```

### 问题:磁盘空间被日志吃了

```powershell
# 查看大小
Get-ChildItem data -Recurse | Measure-Object Length -Sum

# WAL 文件可能很大(临时),安全清理:
Remove-Item data\*.db-wal, data\*.db-shm -ErrorAction SilentlyContinue
# 下次服务启动会自动重建
```

---

## 附录:命令速查

```powershell
# === 启动 ===
$env:JWT_SECRET_KEY="xxx"; $env:ADMIN_TOKEN="yyy"
uvicorn cagent_os.interfaces.http.app:create_app --factory --port 8000

# === 邀请码 ===
python scripts/generate_invitation_codes.py --count 10
python scripts/generate_invitation_codes.py --list-available

# === 用户管理 ===
python scripts/manage_users.py list
python scripts/manage_users.py list --active
python scripts/manage_users.py disable <username>
python scripts/manage_users.py enable <username>
python scripts/manage_users.py invitations

# === 备份 ===
Compress-Archive -Path data -DestinationPath "backup-$(Get-Date -Format yyyyMMdd).zip"

# === 健康检查 ===
curl http://127.0.0.1:8000/health
```

---

## 下一步

- [ ] **PIN 暴力破解防护**:加 login 限流(5 次/分钟)
- [ ] **Web 控制台**:替代 CLI,提供图形化管理界面
- [ ] **邮件重置 PIN**:接 SMTP,用户自助重置
- [ ] **审计日志**:记录所有 admin 操作
- [ ] **部署上线**:Docker + Nginx + HTTPS
