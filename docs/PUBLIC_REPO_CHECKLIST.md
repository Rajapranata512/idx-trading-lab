# Public Repo Checklist

Use this checklist before making the repository public.

## 1. Secrets and credentials

- Ensure `.env` is not tracked.
- Keep only placeholders in `.env.example`.
- Confirm no real tokens are present in committed files.
- Rotate credentials immediately if a secret was accidentally pushed.

## 2. n8n workflow export hygiene

- Do not commit real `chatId` values.
- Do not commit local n8n credential IDs.
- Keep Telegram target as env expression:
  - `={{$env.TELEGRAM_CHAT_ID || ''}}`

## 3. Data licensing and privacy

- Do not commit proprietary/raw market dumps by default.
- Commit sample/synthetic data only when possible.
- Keep local raw file out of git:
  - `data/raw/prices_daily.csv`

## 4. Local safety checks

```powershell
rg -n --hidden -S "(api[_-]?key|token|secret|password|bearer|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|EODHD_API_TOKEN)" .
git ls-files
```

## 5. GitHub repo settings

- Enable Secret Scanning.
- Enable Dependabot Security Updates.
- Protect `main` branch (PR required + status checks).
- Add CODEOWNERS if collaborating in a team.
