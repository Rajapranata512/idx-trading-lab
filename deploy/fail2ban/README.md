# Fail2ban Preset for Ops Routes

Preset ini dipakai untuk memonitor route operasional yang paling sensitif:

- `/ops-login.html`
- `/ops-report.html`
- `/close-analysis.html`
- `/api/jobs`
- `/api/run-daily`
- `/api/report-html`
- `/api/close-analysis`
- `/api/close-prices`

## Cara pakai

1. Pastikan deploy produksi memakai [docker-compose.prod.yml](/c:/TRADING/idx-trading-lab%20-%20Copy/docker-compose.prod.yml) agar log Nginx ditulis ke `./logs/nginx`.
2. Salin filter:

```bash
sudo cp deploy/fail2ban/filter.d/idx-ops-auth.conf /etc/fail2ban/filter.d/idx-ops-auth.conf
```

3. Salin jail example lalu sesuaikan path repo di server:

```bash
sudo cp deploy/fail2ban/jail.d/idx-ops-auth.local.example /etc/fail2ban/jail.d/idx-ops-auth.local
```

4. Restart fail2ban:

```bash
sudo systemctl restart fail2ban
sudo fail2ban-client status idx-ops-auth
```

## Apa yang dianggap abuse

Filter ini akan menghitung respons `401`, `403`, atau `429` pada route ops di atas. Itu membuat kita bisa:

- mem-ban IP yang terus mencoba login salah
- mem-ban IP yang menabrak allowlist
- mem-ban IP yang terus menabrak rate-limit atau lockout

## Catatan

- Ini layer tambahan di luar guardrail aplikasi.
- Untuk public domain, kombinasi yang sehat adalah:
  - allowlist IP
  - app-level rate limit
  - temporary lockout
  - fail2ban di host
