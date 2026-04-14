# Binance Alpha 空投监控脚本

这个项目会直接请求 `https://alphac.cc/local_data_api.php?action=today` 和 `https://alphac.cc/local_data_api.php?action=upcoming`，不跑浏览器、不解析动态 DOM，所以资源占用很低，适合低频轮询。

脚本会在以下情况发邮件：

- 出现新的空投预告
- 有空投进入“即将开始”窗口
- 空投状态、时间、积分、数量等字段发生变化
- 原来存在的条目从列表中消失

## 文件说明

- `alpha_monitor.py`: 主脚本，单次执行完成一次检查
- `.env.example`: 环境变量示例
- `alpha_monitor_state.json`: 运行后自动生成，用来记住上次状态

## 配置

建议把敏感信息放进环境变量，不要写死在代码里。

```bash
export ALPHA_REQUEST_TIMEOUT="15"
export ALPHA_TIMEZONE="Asia/Shanghai"
export ALPHA_SMTP_HOST="smtp.qq.com"
export ALPHA_SMTP_PORT="465"
export ALPHA_SMTP_SSL="1"
export ALPHA_SMTP_USER="你的QQ邮箱"
export ALPHA_SMTP_PASSWORD="你的QQ邮箱授权码"
export ALPHA_EMAIL_FROM="你的QQ邮箱"
export ALPHA_EMAIL_TO="收件邮箱"
export ALPHA_SOON_MINUTES="120"
```

如果发件人和收件人是同一个邮箱，只配 `ALPHA_SMTP_USER` 和 `ALPHA_SMTP_PASSWORD` 也可以。

## 运行

先验证接口和邮件配置：

```bash
python3 alpha_monitor.py --test-email
```

正式检查一次：

```bash
python3 alpha_monitor.py
```

只看结果不发邮件：

```bash
python3 alpha_monitor.py --dry-run --verbose
```

## PythonAnywhere 说明

脚本本身兼容 PythonAnywhere 的普通 Python 环境，因为它只依赖标准库。

但是要注意平台限制：

- 2026-04 时点，新的 PythonAnywhere 免费账号没有 scheduled tasks
- 免费账号的外网访问是白名单制，`alphac.cc` 大概率不在白名单里
- 免费账号不能指望直接走 QQ SMTP 做自动发信

所以这份脚本适合以下场景：

- 你有 PythonAnywhere 付费账号
- 你有较早注册、仍带定时能力的旧免费账号，并且目标站点可访问
- 你把脚本部署到本地、VPS、GitHub Actions、其他支持外网和 SMTP 的环境

如果你必须“全自动 + 低成本”，更现实的方案通常是：

1. 付费 PythonAnywhere 计划
2. GitHub Actions / 其他免费 CI 跑脚本
3. 本地 NAS / 轻量服务器 / 云函数

## 建议轮询频率

为了省资源，推荐 10 到 15 分钟执行一次。

这个脚本每次只请求两个 JSON 接口，并且只有发现变化才发邮件，已经尽量压低了流量和 CPU。

默认按 `Asia/Shanghai` 解释页面时间；如果你确认页面时间不是北京时间，可以改 `ALPHA_TIMEZONE`。

## 安全提醒

你刚才给过 QQ 授权码。建议你现在去 QQ 邮箱后台重置一次授权码，然后把新的值只放到环境变量里，不要再写入仓库。
