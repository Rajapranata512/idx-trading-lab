# Deploy Healthcheck Checklist

Checklist ini dipakai setelah stack dijalankan melalui:

- [docker-compose.prod.yml](/c:/TRADING/idx-trading-lab%20-%20Copy/docker-compose.prod.yml)
- [docker-compose.prod.override.yml](/c:/TRADING/idx-trading-lab%20-%20Copy/docker-compose.prod.override.yml)

## 1. Pre-flight

- [ ] `.env` ada dan tidak lagi memakai password placeholder
- [ ] `IDX_PUBLIC_DOMAIN` sudah diisi domain final
- [ ] `LETSENCRYPT_EMAIL` sudah diisi email operasional
- [ ] `IDX_NGINX_TEMPLATE` sudah sesuai tahap:
  - bootstrap: `./deploy/nginx.bootstrap.conf.template`
  - TLS final: `./deploy/nginx.prod.conf.template`
- [ ] Docker Desktop / Docker engine status `running`

## 2. Container health

Jalankan:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml ps
```

Checklist:

- [ ] `idx-web` status `running` atau `healthy`
- [ ] `nginx` status `running` atau `healthy`
- [ ] tidak ada container restart loop

## 3. App health

Langsung dari host:

```bash
curl http://127.0.0.1:8080/api/health
```

Checklist:

- [ ] respons `200`
- [ ] JSON berisi `"status": "ok"`

## 4. Public routing

Via domain publik:

```bash
curl -I http://YOUR_DOMAIN
curl -I https://YOUR_DOMAIN
```

Checklist:

- [ ] HTTP redirect ke HTTPS saat template TLS aktif
- [ ] HTTPS root `200`
- [ ] `/` membuka premium dashboard
- [ ] `/legacy-console.html` memberi `404`

## 5. Operational auth

Checklist:

- [ ] `/ops-login.html` bisa diakses hanya dari IP yang diizinkan
- [ ] `/ops-report.html` butuh auth operasional
- [ ] `/api/jobs` tanpa auth memberi `401`
- [ ] auth salah berulang memicu `429`

Tes cepat:

```bash
curl -i https://YOUR_DOMAIN/api/jobs
curl -i -u ops:WRONGPASS https://YOUR_DOMAIN/api/jobs
```

## 6. TLS

Checklist:

- [ ] `fullchain.pem` dan `privkey.pem` tersedia di volume letsencrypt
- [ ] browser tidak menunjukkan warning sertifikat
- [ ] `Strict-Transport-Security` ada di response header HTTPS

## 7. Logs and abuse monitoring

Checklist:

- [ ] `logs/nginx/idx_access.log` ada
- [ ] `logs/nginx/idx_ops_access.log` ada
- [ ] fail2ban jail `idx-ops-auth` aktif
- [ ] ban test tercatat saat menabrak `401/403/429` berulang

Perintah host:

```bash
sudo fail2ban-client status idx-ops-auth
tail -f logs/nginx/idx_ops_access.log
```

## 8. Trading-specific sanity checks

- [ ] `/api/dashboard` menampilkan snapshot terbaru
- [ ] data `max_date` tidak stale
- [ ] provider source sesuai yang diharapkan
- [ ] premium dashboard tidak membocorkan path lokal atau secret
- [ ] `run-daily` tetap hanya bisa dipanggil dari localhost

## 9. Rollback trigger

Rollback cepat disarankan jika:

- `idx-web` restart loop
- `nginx` gagal load cert/template
- auth operasional unexpectedly open
- route publik menampilkan halaman kosong atau error 5xx berulang

Rollback minimum:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml logs --tail=200
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml down
```
