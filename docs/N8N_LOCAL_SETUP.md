# n8n Local (Non-Cloud) Setup

## Tujuan

Menjalankan n8n di mesin lokal Windows agar workflow bisa mengeksekusi command lokal (`C:\TRADING\idx-trading-lab\scripts\...`) dengan error minimal.

## 1) Install n8n lokal

Jalankan:

`powershell -ExecutionPolicy Bypass -File scripts/install_n8n_local.ps1`

## 2) Validasi env trading

`powershell -ExecutionPolicy Bypass -File scripts/validate_env.ps1`

Wajib terdeteksi:

- `EODHD_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## 3) Start n8n lokal

Foreground:

`powershell -ExecutionPolicy Bypass -File scripts/start_n8n_local.ps1`

Background:

`powershell -ExecutionPolicy Bypass -File scripts/start_n8n_background.ps1`

UI:

`http://127.0.0.1:5678`

Catatan:

- Untuk n8n v2+, node `Execute Command` default bisa nonaktif.
- Script `start_n8n_local.ps1` sudah memaksa `NODES_EXCLUDE=[]` agar node ini aktif.
- Kalau di canvas node muncul tanda `?` dengan error `Unrecognized node type: n8n-nodes-base.executeCommand`, stop n8n lalu start ulang pakai script ini.

## 4) Import workflow

Via CLI:

`powershell -ExecutionPolicy Bypass -File scripts/import_workflow_local.ps1`

Atau via UI:

Import file `n8n/workflows/idx_trading_daily.json`.

## 5) Set Telegram credential di n8n

Di node `Telegram Status`:

1. Create/select credential `Telegram API`
2. Isi token bot
3. Pastikan env `TELEGRAM_CHAT_ID` tersedia untuk proses n8n
4. Save workflow

## 6) Auto-start saat Windows login

Daftarkan task:

`powershell -ExecutionPolicy Bypass -File scripts/register_n8n_startup_task.ps1`

Catatan:

- Script akan coba `RunLevel=Highest` dulu.
- Jika akses ditolak (`0x80070005`), script otomatis fallback ke `RunLevel=Limited` (tanpa admin).
- Jika `ScheduledTask` tetap ditolak oleh policy local, script otomatis membuat launcher di folder Startup user:
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\IDX_N8N_Local_Startup.cmd`

Hapus task:

`powershell -ExecutionPolicy Bypass -File scripts/unregister_n8n_startup_task.ps1`

## 7) Operasional harian

- Backfill awal:
  `powershell -ExecutionPolicy Bypass -File scripts/backfill_2y.ps1`
- Test harian:
  `powershell -ExecutionPolicy Bypass -File scripts/run_daily_retry.ps1`
- Keputusan cepat trading:
  `powershell -ExecutionPolicy Bypass -File scripts/ops_daily_check.ps1`

Output ringkas:

- `reports/n8n_last_summary.json`

## 8) Status penting

- `SUCCESS`: ada sinyal dan gate lolos.
- `NO_SIGNAL`: run sukses tapi sinyal eksekusi kosong.
- `BLOCKED_BY_GATE`: backtest belum layak live.
- `STALE_DATA`: data terbaru terlalu lama.
- `PARTIAL_DATA`: banyak ticker missing.
- `FAILED`/`SETUP_ERROR`: perlu perbaikan sistem.
