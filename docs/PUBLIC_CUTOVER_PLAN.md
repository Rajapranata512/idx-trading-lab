# Public Cutover Plan

Dokumen ini merangkum langkah cutover dari localhost / private preview ke domain publik dengan downtime seminimal mungkin.

## Tujuan

- premium dashboard tetap read-only dan publik
- route ops tetap terkunci
- transisi dilakukan tanpa mengganggu pipeline riset harian

## Fase 1: Freeze dan snapshot

Sebelum cutover:

1. pastikan run harian terakhir sukses
2. simpan backup:
   - `config/settings.json`
   - `.env`
   - `reports/`
3. catat kondisi baseline:
   - `/api/health`
   - `/api/dashboard`
   - current auth posture

Checklist:

- [ ] tidak ada run aktif yang tertinggal
- [ ] backup selesai
- [ ] baseline response tercatat

## Fase 2: Parallel deploy

Deploy stack publik secara paralel, jangan langsung mematikan localhost setup.

1. isi `.env` server publik
2. mulai dengan bootstrap nginx template
3. jalankan:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml up -d idx-web nginx
```

4. verifikasi internal:

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1
```

Checklist:

- [ ] app up
- [ ] premium dashboard tampil
- [ ] route ops tetap locked

## Fase 3: TLS bootstrap

1. arahkan DNS domain ke host publik
2. tunggu propagasi DNS
3. issue cert pertama:

```bash
docker compose -f docker-compose.prod.yml --profile certbot-init run --rm certbot-init
```

4. ubah `.env`:

```text
IDX_NGINX_TEMPLATE=./deploy/nginx.prod.conf.template
```

5. reload nginx:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.prod.override.yml up -d nginx
docker compose -f docker-compose.prod.yml --profile tls up -d certbot-renew
```

Checklist:

- [ ] HTTPS valid
- [ ] HTTP redirect ke HTTPS
- [ ] HSTS header aktif

## Fase 4: Soft launch

Sebelum diumumkan publik luas:

1. uji dari jaringan luar
2. uji auth ops dari IP yang memang diizinkan
3. pantau:
   - `docker compose ps`
   - `docker compose logs`
   - fail2ban status
   - `logs/nginx/idx_ops_access.log`

Checklist:

- [ ] root domain sehat
- [ ] `/legacy-console.html` tetap 404
- [ ] `/ops-login.html` sesuai allowlist
- [ ] tidak ada 5xx spike

## Fase 5: Cutover final

Kalau sebelumnya ada reverse proxy atau instance lama:

1. turunkan TTL DNS sebelum hari H
2. cut traffic ke host/container baru
3. monitor 30-60 menit pertama secara aktif

Pantau:

- response time
- container restarts
- auth failures
- rate-limit hits
- stale data indicators di dashboard

## Fase 6: Rollback

Kalau ada masalah setelah cutover:

1. rollback DNS / reverse proxy ke target lama
2. simpan log insiden
3. hentikan publikasi dulu
4. analisis:
   - auth leak
   - TLS error
   - route mismatch
   - data freshness issue

## Rekomendasi downtime minimum

Untuk menekan downtime:

- lakukan deploy paralel
- issue cert sebelum publikasi besar
- jangan edit config langsung di container
- gunakan volume bind untuk `config`, `data`, `reports`, `models`
- siapkan rollback DNS atau reverse proxy upstream

## Setelah cutover

Setelah stabil:

- aktifkan rotasi password ops berkala
- review fail2ban bans mingguan
- review rate-limit numbers berdasarkan traffic nyata
- dokumentasikan host, domain, dan secret owner
