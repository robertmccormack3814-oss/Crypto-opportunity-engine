# ASX Regime-Aware Opportunity Engine v1

Routes each ASX primary listed equity into TREND, RANGE, SQUEEZE or UNCLEAR.

Modules:
- Trend/Breakout
- Mean Reversion
- Volatility Squeeze/Expansion
- OHLCV microstructure/order-flow proxies

Execution-risk gates:
- 20-day average dollar volume
- ATR%
- latest gap%
- optional bid/ask spread estimate
- configurable macro blackout dates

Every accepted alert includes:
- ticker/company
- direction
- regime and strategy
- signal score
- entry
- ATR-derived stop
- dynamic target in R
- position sizing (units per A$100k, plus actual units if account equity is configured)

Active trades are tracked for:
- hard stop
- profit target
- ATR trailing stop on trend trades
- time exit

Important: v1 uses free/public OHLCV data. Its microstructure layer uses volume/price proxies, not true Level 2 order-book flow.

GitHub secrets:
- SMTP_USERNAME
- SMTP_APP_PASSWORD
- optional ALERT_WEBHOOK_URL

Set Settings > Pages > Source = GitHub Actions.
