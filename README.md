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

## 本地运行

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

## GitHub Actions 部署

仓库里已经包含半小时执行一次的 workflow：

- `.github/workflows/alpha-monitor.yml`

它会做三件事：

- 每 30 分钟执行一次监控
- 发现变化时发送 QQ 邮件
- 自动把 `alpha_monitor_state.json` 提交回仓库，保证下次运行还能继续做差异对比

### 你需要在 GitHub 仓库里配置的 Secret

进入仓库：

`Settings -> Secrets and variables -> Actions -> New repository secret`

添加下面这个 secret：

- `ALPHA_SMTP_PASSWORD`: 你的 QQ 邮箱授权码

### Workflow 默认配置

workflow 已经默认写好这些值：

- 发件邮箱: `2386104975@qq.com`
- 收件邮箱: `2386104975@qq.com`
- SMTP: `smtp.qq.com:465`
- 轮询频率: 每 30 分钟
- 时区解释: `Asia/Shanghai`

如果你后面想改收件邮箱或发件邮箱，可以直接改 workflow 里的 env。

### 启用方式

1. 把当前目录推到 GitHub 仓库。
2. 在仓库 Secrets 里新增 `ALPHA_SMTP_PASSWORD`。
3. 进入 `Actions` 页面，启用 workflow。
4. 手动点一次 `Run workflow` 做首轮测试。

### 如何测试邮件是否可发

在 `Actions -> Alpha Monitor -> Run workflow` 里把 `send_test_email` 选成 `true`，然后运行一次。

如果配置正确，你会立刻收到一封主题为 `[Alpha监控] 测试邮件` 的邮件。

## 轮询频率

当前 workflow 是每 30 分钟执行一次。

这个脚本每次只请求两个 JSON 接口，并且只有发现变化才发邮件，资源占用很低，适合 GitHub Actions 这种短时任务环境。

默认按 `Asia/Shanghai` 解释页面时间；如果你确认页面时间不是北京时间，可以改 `ALPHA_TIMEZONE`。

## 安全提醒

QQ 授权码不要写进仓库，只放到 GitHub Secrets 里。
