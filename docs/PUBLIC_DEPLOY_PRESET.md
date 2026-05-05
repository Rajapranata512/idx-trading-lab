# Public Deploy Preset

Dokumen ini merangkum preset deploy publik yang lebih aman untuk **IDX Trading Lab** setelah perubahan web terbaru:

- `/` sekarang mengarah ke **premium dashboard** publik
- legacy console sudah dinonaktifkan dari server
- area operasional memakai **login ringan** di [ops-login.html](/c:/TRADING/idx-trading-lab%20-%20Copy/web/ops-login.html)
- route operasional sensitif dapat diproteksi dengan:
  - `IDX_WEB_USERNAME`
  - `IDX_WEB_PASSWORD`
- `run-daily` tetap hanya bisa dijalankan dari **localhost**

## 1. Prinsip Deploy yang Disarankan

Untuk hosting publik, pola yang paling aman adalah:

1. jalankan Python web server hanya di `127.0.0.1:8080`
2. letakkan Nginx atau reverse proxy di depan aplikasi
3. ekspos hanya reverse proxy ke internet
4. aktifkan auth operasional melalui environment variable
5. gunakan premium dashboard sebagai halaman publik

Catatan:

- `src.cli` dan `src.web.server` sekarang otomatis mencoba memuat file `.env` dari working directory saat start
- jadi service runner cukup memastikan `WorkingDirectory` benar dan file `.env` tersedia

## 2. Environment Variable Minimum

Gunakan file [.env.example](/c:/TRADING/idx-trading-lab%20-%20Copy/.env.example) sebagai template dasar.

Untuk systemd, contoh file service dan env ada di:

- [deploy/systemd/idx-web.service.example](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/systemd/idx-web.service.example)
- [deploy/systemd/idx-web.env.example](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/systemd/idx-web.env.example)
- [deploy/systemd/install_idx_web_service.sh](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/systemd/install_idx_web_service.sh)

Variable penting:

- `EODHD_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `IDX_WEB_USERNAME`
- `IDX_WEB_PASSWORD`
- `IDX_WEB_OPS_LOGIN_ALLOWLIST`
- `IDX_WEB_OPS_LOGIN_RATE_LIMIT_MAX_REQUESTS`
- `IDX_WEB_OPS_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `IDX_WEB_AUTH_LOCKOUT_MAX_FAILURES`
- `IDX_WEB_AUTH_LOCKOUT_SECONDS`

Untuk public deploy, `IDX_WEB_USERNAME` dan `IDX_WEB_PASSWORD` sebaiknya **selalu diisi**.

## 3. Jalankan Web Server di Loopback

Contoh:

```powershell
$env:IDX_WEB_USERNAME="ops"
$env:IDX_WEB_PASSWORD="ganti-password-kuat"
.\.venv\Scripts\python.exe -m src.cli --settings config/settings.json serve-web --host 127.0.0.1 --port 8080
```

Kenapa `127.0.0.1`:

- aplikasi backend tidak langsung terekspos ke internet
- semua traffic publik dipaksa lewat reverse proxy
- kontrol TLS, rate limit, dan logging jadi lebih rapi

## 4. Reverse Proxy Notes

Contoh konfigurasi Nginx disediakan di:

- [deploy/nginx.public.conf.example](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/nginx.public.conf.example)
- [deploy/nginx.bootstrap.conf.template](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/nginx.bootstrap.conf.template)
- [deploy/nginx.prod.conf.template](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/nginx.prod.conf.template)

Tujuan reverse proxy:

- terminasi HTTPS/TLS
- header security
- rate limit ringan untuk endpoint operasional
- memisahkan akses publik dan akses operasional

## 4a. Docker Compose Produksi

File yang disiapkan:

- [docker-compose.prod.yml](/c:/TRADING/idx-trading-lab%20-%20Copy/docker-compose.prod.yml)
- [docker-compose.prod.override.yml](/c:/TRADING/idx-trading-lab%20-%20Copy/docker-compose.prod.override.yml)
- [deploy/init-letsencrypt.sh.example](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/init-letsencrypt.sh.example)

Variable tambahan yang perlu diisi di `.env`:

- `IDX_PUBLIC_DOMAIN`
- `LETSENCRYPT_EMAIL`
- `IDX_NGINX_TEMPLATE`

Alur yang disarankan:

1. mulai dengan:
   - `IDX_NGINX_TEMPLATE=./deploy/nginx.bootstrap.conf.template`
2. jalankan stack awal:

```bash
docker compose -f docker-compose.prod.yml up -d idx-web nginx
```

3. issue sertifikat pertama:

```bash
docker compose -f docker-compose.prod.yml --profile certbot-init run --rm certbot-init
```

4. ubah `.env` menjadi:
   - `IDX_NGINX_TEMPLATE=./deploy/nginx.prod.conf.template`
5. reload Nginx:

```bash
docker compose -f docker-compose.prod.yml up -d nginx
```

6. aktifkan renewal loop:

```bash
docker compose -f docker-compose.prod.yml --profile tls up -d certbot-renew
```

Catatan:

- `idx-web` tidak dipublish langsung ke internet pada compose produksi
- hanya Nginx yang membuka port `80/443`
- log Nginx ditulis ke `./logs/nginx` agar bisa dimonitor host

## 5. Route Publik vs Operasional

### Publik

- `/`
- `/premium-dashboard.html`

Halaman ini dirancang untuk konsumsi publik/read-only.

### Operasional

- `/ops-login.html`
- `/ops-report.html`
- `/close-analysis.html`
- `/report`
- `/api/report-html`
- `/api/jobs`
- `/api/jobs/{id}`
- `/api/run-daily`
- `/api/close-analysis`
- `/api/close-prices`

Catatan:

- `close-analysis.html` adalah shell halaman operasional
- data operasionalnya tetap dikunci oleh auth API
- `run-daily` tetap **localhost-only** walaupun auth benar

## 6. Alur Operator yang Disarankan

1. buka `https://domain-kamu/ops-login.html`
2. login dengan kredensial operasional
3. dari halaman itu:
   - buka close analysis
   - buka report operasional
   - cek status jobs
   - trigger `run-daily` bila sedang di localhost

Keuntungan model ini:

- public dashboard tetap bersih
- operator punya jalur kerja yang jelas
- area sensitif tidak diiklankan dari halaman publik

## 7. Hardening Checklist

Checklist minimum sebelum go-live publik:

- [ ] app backend bind ke `127.0.0.1`, bukan `0.0.0.0`
- [ ] `IDX_WEB_USERNAME` dan `IDX_WEB_PASSWORD` terisi
- [ ] `IDX_WEB_OPS_LOGIN_ALLOWLIST` diisi bila operator berasal dari IP/range yang tetap
- [ ] `IDX_WEB_OPS_LOGIN_RATE_LIMIT_MAX_REQUESTS` dan `IDX_WEB_OPS_LOGIN_RATE_LIMIT_WINDOW_SECONDS` ditinjau ulang untuk traffic produksi
- [ ] `IDX_WEB_AUTH_LOCKOUT_MAX_FAILURES` dan `IDX_WEB_AUTH_LOCKOUT_SECONDS` ditinjau ulang agar tidak terlalu longgar atau terlalu agresif
- [ ] password operasional kuat dan tidak dipakai ulang
- [ ] TLS/HTTPS aktif di reverse proxy
- [ ] rate limiting aktif untuk route operasional
- [ ] file `.env` atau secret manager tidak ikut ke repo
- [ ] `config/settings.json` tidak berisi token nyata
- [ ] akses `run-daily` tetap diuji dari localhost saja
- [ ] premium dashboard dicek ulang untuk memastikan tidak ada path lokal, token, atau detail internal yang bocor
- [ ] reports sensitif tidak diekspos langsung sebagai static directory listing

Checklist tambahan yang direkomendasikan:

- [ ] pasang allowlist IP untuk `/ops-login.html` jika operator sedikit
- [ ] taruh web app di belakang WAF/CDN bila trafik publik tinggi
- [ ] tambahkan log monitoring untuk 401/403 yang berulang
- [ ] lakukan rotasi password operasional berkala
- [ ] aktifkan fail2ban host-level untuk log ops Nginx

## 7a. Fail2ban / Abuse Monitoring

Preset fail2ban tersedia di:

- [deploy/fail2ban/filter.d/idx-ops-auth.conf](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/fail2ban/filter.d/idx-ops-auth.conf)
- [deploy/fail2ban/jail.d/idx-ops-auth.local.example](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/fail2ban/jail.d/idx-ops-auth.local.example)
- [deploy/fail2ban/README.md](/c:/TRADING/idx-trading-lab%20-%20Copy/deploy/fail2ban/README.md)

Preset ini fokus mem-ban IP yang berulang kali memicu `401`, `403`, atau `429` pada route ops.

## 9a. Dokumen Operasional Tambahan

Untuk go-live yang lebih tertib, gunakan juga:

- [docs/DEPLOY_HEALTHCHECK_CHECKLIST.md](/c:/TRADING/idx-trading-lab%20-%20Copy/docs/DEPLOY_HEALTHCHECK_CHECKLIST.md)
- [docs/PUBLIC_CUTOVER_PLAN.md](/c:/TRADING/idx-trading-lab%20-%20Copy/docs/PUBLIC_CUTOVER_PLAN.md)

## 8. Batasan yang Perlu Dipahami

Proteksi saat ini adalah **lightweight operational auth**, bukan sistem IAM penuh.

Artinya:

- cocok untuk project riset / internal / semi-publik
- belum menggantikan SSO, RBAC, audit trail user-level, atau session management enterprise

Kalau project ini nanti naik kelas menjadi aplikasi publik penuh dengan banyak operator, langkah berikutnya yang sehat adalah:

1. pindah ke auth/session yang lebih formal
2. tambah role-based access
3. pisahkan frontend publik dan panel operator secara eksplisit

## 9. Rekomendasi Praktis

Untuk kondisi project sekarang, setup paling seimbang adalah:

- **publik**: premium dashboard read-only
- **operator**: `ops-login.html`
- **report operasional**: `ops-report.html`
- **backend**: loopback only
- **reverse proxy**: Nginx + TLS + rate limit
- **ops abuse protection**: allowlist + rate-limit + temporary lockout

Itu memberi kombinasi yang cukup aman, cukup sederhana, dan tetap mudah dioperasikan.
