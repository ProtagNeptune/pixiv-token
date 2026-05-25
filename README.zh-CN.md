# Pixiv OAuth Token Fetcher

🌍 [English](README.md) | [简体中文](README.zh-CN.md)

Python 自动化工具，模拟 Pixiv OAuth 登录流程，提取授权码并换取 access_token。

---

## 📦 功能亮点

- ✅ 自动化模拟 Pixiv 登录流程（用户名密码）
- ✅ 支持无头模式
- ✅ 支持窗口模式（非无头）
- ✅ 通过 CDP 在控制台捕获授权码
- ✅ 获取 access_token 与 refresh_token
- ✅ 缓慢输入模拟真人操作，绕过机器人检测
- ✅ 自动跳过安全设置提示页面（Passkeys / 2FA 提醒）
- ✅ 多选择器兼容 Pixiv 登录表单变化
- ✅ Token 缓存 + 自动刷新（仅首次或 refresh token 失效时才打开浏览器登录）
- ✅ 多账号支持（每个邮箱单独缓存于 `~/.pixiv-token/`）
- ✅ 机器可读输出（`--json` / `--print <字段>`），结果走 stdout，日志走 stderr
- ✅ 使用标准 `logging`，库默认静音，消费者可接入自己的 handler
- ✅ 可作为库安装（`pip install .`）并提供 `pixiv-token` 命令

---

## 🚀 安装方式

### 1. 克隆项目

```bash
git clone https://github.com/piglig/pixiv-token.git
cd pixiv-token
```

### 2. 安装依赖

推荐 Python 版本：`>=3.8`

```bash
# 源码模式开发
pip install -r requirements.txt

# 或者安装为包（同时注册 `pixiv-token` 命令）
pip install .
```

---

## ⚙️ 使用方法

### 命令行方式

```bash
# 某账号首次运行 —— 需要账号密码，执行浏览器登录并缓存 token
python pixiv_token_fetcher.py -u "你的邮箱" -p "你的密码"

# 后续运行 —— 直接使用缓存；过期时自动用 refresh_token 续期
# （只有一个账号时自动选中）
python pixiv_token_fetcher.py

# 多账号场景 —— 指定使用哪个已缓存账号
python pixiv_token_fetcher.py --account "你的邮箱"

# 列出所有已缓存账号及其过期时间
python pixiv_token_fetcher.py --list-accounts

# 显示浏览器窗口（登录场景）
python pixiv_token_fetcher.py -u "你的邮箱" -p "你的密码" --no-headless

# 强制重新登录（忽略缓存）
python pixiv_token_fetcher.py -u "你的邮箱" -p "你的密码" --force-login

# 自定义缓存目录
python pixiv_token_fetcher.py --cache-dir ./tokens

# 机器可读：完整记录以 JSON 输出到 stdout（状态日志走 stderr）
python pixiv_token_fetcher.py --json

# 适合管道：只输出某个字段的原始值（无标签、无 emoji）
ACCESS_TOKEN=$(python pixiv_token_fetcher.py --print access_token)
REFRESH=$(python pixiv_token_fetcher.py --print refresh_token)

# 日志级别（日志只写到 stderr）
python pixiv_token_fetcher.py --verbose   # debug 级别
python pixiv_token_fetcher.py --quiet     # 仅 warning / error

# 通过 `pip install .` 安装后，可直接使用 `pixiv-token` 命令
pixiv-token --print access_token
```

默认缓存目录：`~/.pixiv-token/`，每个账号一个文件（`<邮箱>.json`），内含 `username`、`access_token`、`refresh_token`、`expires_at`，请按凭证级别保管。

### 作为模块调用

```python
from pixiv_token_fetcher import PixivTokenFetcher

# 首次登录某账号 —— 需要密码
fetcher = PixivTokenFetcher(
    username="你的Pixiv账号",
    password="你的Pixiv密码",
    headless=True,
)
token = fetcher.get_token()  # 缓存 → 刷新 → 浏览器登录 （按此顺序回退）
print(token["access_token"])

# 之后无需密码，直接复用缓存
fetcher = PixivTokenFetcher(account="你的Pixiv账号")
token = fetcher.get_token()

# 列出所有已缓存账号
for acc in PixivTokenFetcher().list_cached_accounts():
    print(acc["username"], acc["expires_at"])
```

返回的 `token` 始终包含 `username`、`access_token`、`refresh_token`、`expires_at`（Unix 秒）四个字段。

日志：库使用标准 `logging` 模块，logger 名为 `pixiv_token_fetcher`，**默认不挂任何 handler**（导入时完全静音），由调用方接入：

```python
import logging
logging.getLogger("pixiv_token_fetcher").setLevel(logging.INFO)
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
```

---

## 🔧 工作原理

1. **缓存读取** — 解析账号（显式 `--account` / `--username`，或仅一个缓存时自动选中）后读取 `~/.pixiv-token/<邮箱>.json`；若 `access_token` 仍在有效期内，直接返回
2. **自动刷新** — 若 access token 已过期，调用 Pixiv 的 `grant_type=refresh_token` 接口续期并写回缓存（无需启动浏览器）
3. **PKCE 生成** *(回退路径)* — 生成 `code_verifier` 和 `code_challenge` 用于 OAuth PKCE 流程
4. **浏览器启动** — 启动隐身 Chromium 执行登录
5. **自动登录** — 以缓慢输入方式填写邮箱和密码，模拟真人操作
6. **授权码捕获** — 通过 CDP（`Network.requestWillBeSent`）拦截 `pixiv://account/login?code=...` 重定向
7. **安全提示处理** — 若 Pixiv 弹出 Passkeys/2FA 设置页面，自动点击"稍后提醒"/"跳过"
8. **Token 交换** — 通过 Pixiv OAuth API 将授权码换取 access token 和 refresh token，并写入缓存

---

## 📌 注意事项

- ⚠️ 请勿在生产环境中硬编码账号密码，建议使用环境变量或密钥管理工具。
- ❌ 本项目非 Pixiv 官方 SDK，Pixiv 页面结构变化可能影响运行。
- 🛡 使用时请遵守 Pixiv 的服务条款。
- 🔁 Refresh token 有效期很长，通常只需运行一次即可。

---

## 🧪 示例输出

```
[INFO] opening pixiv login page
[INFO] filled username field
[INFO] filled password field
[INFO] submitted login form
[INFO] skipping security prompt via 'Remind me later' button
[INFO] captured authorization code
access_token:  xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
refresh_token: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
expires_at:    2026-05-25 14:32:10
```

`[INFO]` 行是日志（写到 stderr），`access_token` / `refresh_token` / `expires_at` 是结果（写到 stdout），方便管道使用。

---

## 🧪 测试

单元测试覆盖非浏览器逻辑（缓存读写、账号解析、token 刷新编排、CLI 输出契约）。浏览器流程已 mock，整套测试在 1 秒内跑完，不需要本机安装 CloakBrowser / Playwright。

```bash
pip install -e ".[test]"
pytest
```

## 📝 授权协议

MIT License

---

## 🙋‍♀️ 贡献与反馈

欢迎提交 Pull Request 和 Issue！

---

## 📫 联系方式

- GitHub: [piglig](https://github.com/piglig)
- Email: zhu1197437384@gmail.com
