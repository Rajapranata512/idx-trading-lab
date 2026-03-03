# Reference Universe

`universe_lq45_idx30.csv` is the static universe used by the pipeline.
Update this file manually on a weekly basis to align with IDX index membership changes.

If `data.universe_auto_update.enabled=true`, pipeline will try to refresh this file
weekly from configured URLs (`settings.json`), then fallback to existing file when
URLs are not configured or request fails.

`event_risk_blacklist.csv` is used to block risky tickers from live signals.
Supported statuses are controlled in `pipeline.event_risk.active_statuses`.
The file can also be refreshed automatically using `pipeline.event_risk.auto_update`
or manually using `python -m src.cli update-event-risk --force`.
