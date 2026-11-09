# A股指数行情数据仓库

自动获取上证指数、沪深300、创业板指、深证成指的历史行情，供 ChatGPT「A股分析助手」研究使用。

## 数据源与免责声明

数据来自 AKShare `index_zh_a_hist` 所调用的第三方公开行情接口，不是交易所直连，也不保证实时、准确或持续可用。禁止将本仓库用于自动交易或把延迟数据宣称为实时行情。请遵守上游数据许可与使用条件。

## 使用

- 在 GitHub 仓库的 **Actions** 页找到 `Update A-share index market data`，点击 **Run workflow** 手动运行首次采集。
- 自动计划：每周一至周五北京时间 **16:20**（GitHub 计划任务可能延迟、漏跑，节假日不自动区分）。
- 数据成功生成后位于 `data/`，每个指数有 `_daily.csv/.json`、`_indicators.csv/.json`、`_weekly.csv`、`_monthly.csv`。
- `data/manifest.json` 给出实际最后交易日期、采集时间和行数。**行情日期不等于采集时间**；非交易日可能沿用上一个交易日数据。
- 初始采集要求每个指数至少300条连续的交易日记录，最多保存420条，足以计算 MA250；如果数据异常或接口失效，任务会失败，不会用空值伪造数据。

## 本地运行（可选）

```bash
pip install -r requirements.txt
python scripts/update_data.py
```

## 已计算指标

MA5、MA10、MA20、MA60、MA120、MA250，MACD DIF/DEA/柱状值（柱状值为2×差值），RSI14。MACD/RSI采用常见计算约定，可能与不同行情软件的初值和舍入规则略有差异。周/月线由日线聚合，**最新未结束的周/月为不完整周期**。

## 重要限制

1. GitHub Actions是收盘后更新，不是实时行情推送，也不是MCP服务。
2. 本仓库暂不包含PE、PB估值分位和行情接口容错切换。
3. 若仓库公开，行情文件将公开可读；ChatGPT是否能够自动读取公开文件仍需实际验证。
4. 如 GitHub 工作流无写入权限，在仓库 `Settings → Actions → General → Workflow permissions` 设置适当的读写权限，并检查仓库/组织政策。
