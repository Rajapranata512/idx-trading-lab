# AI Project Context Pack - IDX Trading Lab

Ini adalah halaman indeks untuk agent AI. Jangan langsung membaca semua file proyek. Pilih bagian yang sesuai dengan tugas agar hemat token dan tetap akurat.

Jika hanya punya sedikit context, baca file ini dulu, lalu ambil 1-2 file dari `docs/ai-context/` yang paling relevan.

## Protokol Setelah Token Reset

Jika agent kehilangan konteks, jangan memulai ulang dengan membaca seluruh repository. Ikuti urutan ini:

1. Baca file ini sampai selesai.
2. Identifikasi tugas user: konsep, operasi, debugging, coding, testing, deployment, atau GitHub.
3. Baca hanya `docs/ai-context/00-agent-reading-guide.md`.
4. Pilih maksimal 1-2 dokumen tambahan dari `docs/ai-context/` sesuai rute baca cepat di bawah.
5. Baca kode hanya pada modul yang akan disentuh.
6. Baca test terdekat sebelum atau sesudah edit.
7. Jangan membuka `reports/`, `data/`, `web/reports/`, atau log besar kecuali tugasnya memang debugging output spesifik.

Target context awal setelah reset:

- memahami tujuan proyek,
- tahu entry point utama,
- tahu output yang relevan,
- tahu file mana yang boleh diabaikan,
- tahu test yang perlu dijalankan.

Tidak perlu memahami seluruh kode dari awal jika tugasnya sempit.

## Product Intent Singkat

Project ini adalah decision-support system untuk trading saham IDX, bukan bot eksekusi broker. Tujuan utama:

- memilih kandidat saham secara disiplin,
- memblokir trade saat edge/risk tidak mendukung,
- menghasilkan laporan harian dan dashboard,
- mengukur kualitas sinyal lewat backtest, walk-forward, reconciliation, profit quality, dan signal accuracy audit,
- menjaga pipeline tetap observable dan aman untuk produksi.

Prioritas produk saat ini:

1. Akurasi dan ketajaman sinyal.
2. Risk gate dan no-trade yang sehat.
3. Kualitas data dan observability pipeline.
4. Evaluasi outcome realistis setelah fee/slippage.
5. Perubahan kecil yang teruji, bukan refactor besar tanpa kebutuhan.

Di luar scope kecuali user meminta eksplisit:

- eksekusi order otomatis ke broker,
- melemahkan threshold/risk gate agar sinyal lebih banyak,
- menghapus data/report historis,
- membaca atau mengubah secret,
- redesign besar UI/web tanpa kebutuhan operasional.

## Rute Baca Cepat

Untuk memahami proyek secara umum:

1. `docs/ai-context/00-agent-reading-guide.md`
2. `docs/ai-context/01-project-overview.md`

Untuk mengubah pipeline harian:

1. `docs/ai-context/00-agent-reading-guide.md`
2. `docs/ai-context/03-daily-workflow-run-daily.md`
3. `src/cli.py`
4. Test terkait di `tests/`

Untuk mengubah config, provider data, atau output file:

1. `docs/ai-context/02-repository-map-and-config.md`
2. `src/config.py`
3. Modul terkait di `src/ingest/`, `src/risk/`, atau `src/report/`

Untuk debugging `NO_SIGNAL`, gate, dashboard, atau report:

1. `docs/ai-context/05-operations-and-debugging.md`
2. `reports/signal_funnel_live.json`
3. `reports/backtest_metrics.json`
4. Run log terbaru di `reports/run_log_YYYYMMDD.json`

Untuk evaluasi akurasi sinyal atau profit/loss:

1. `docs/ai-context/00-agent-reading-guide.md`
2. `docs/ai-context/04-module-workflows.md`
3. `src/analytics/signal_accuracy.py`
4. `src/risk/profit_quality.py`
5. `tests/test_signal_accuracy.py` atau `tests/test_profit_quality.py`

Untuk perubahan kode yang aman:

1. `docs/ai-context/06-change-guide-and-tests.md`
2. Modul yang sedang diubah
3. Test yang paling dekat dengan area tersebut

## Daftar Bagian

| Bagian | Isi | Kapan Dibaca |
|---|---|---|
| `00-agent-reading-guide.md` | Strategi hemat token, file yang perlu dan tidak perlu dibaca | Selalu baca pertama |
| `01-project-overview.md` | Gambaran proyek, prinsip, output utama | Saat butuh konteks bisnis/arsitektur |
| `02-repository-map-and-config.md` | Struktur folder, entry point, config, env, kontrak data | Saat menyentuh wiring/config/data |
| `03-daily-workflow-run-daily.md` | Alur `run-daily` sangat detail | Saat mengubah pipeline utama |
| `04-module-workflows.md` | Detail workflow tiap modul | Saat mengubah modul tertentu |
| `05-operations-and-debugging.md` | SOP harian, no-signal, provider, dashboard, output | Saat operasi/debugging |
| `06-change-guide-and-tests.md` | Aturan perubahan kode, test map, dependency | Saat coding/refactor |

## Kontrak Perilaku Agent

Agent harus menjaga fokus terhadap tujuan user terbaru. Jika konteks lama bertentangan dengan pesan user terbaru, pesan terbaru menang.

Sebelum membaca banyak file, agent harus menjawab internal:

1. Apa output yang diminta user?
2. Apakah ini butuh edit kode, edit docs, run command, atau hanya analisis?
3. Modul apa yang mungkin berubah?
4. File besar apa yang bisa dihindari?
5. Validasi minimal apa yang cukup?

Agent tidak boleh melakukan kegiatan sampingan seperti redesign, refactor besar, push GitHub, atau deployment kecuali user meminta eksplisit.

## Prinsip Context Hemat Token

Mulai dari pertanyaan ini:

1. Tugasnya konsep, operasi, debugging, atau coding?
2. Modul mana yang benar-benar disentuh?
3. Output mana yang berubah?
4. Test mana yang paling dekat?

Hindari membaca file besar di awal:

- `web/reports/snapshots/*.json`
- `web/reports/run_log_*.json`
- `reports/*.log`
- `tmp_*.log`
- `data/raw/prices_daily.csv`
- `data/raw/prices_intraday.csv`
- artifact model di `models/`

File besar itu hanya dibaca saat benar-benar dibutuhkan untuk debugging spesifik.

## Mental Model Singkat

IDX Trading Lab adalah decision-support system untuk trading saham Indonesia. Sistem mengambil data harga, memvalidasi data, menghitung fitur, menilai kandidat `t1` dan `swing`, lalu menerapkan risk gate sebelum menghasilkan sinyal final.

Sistem ini bukan bot broker. Eksekusi order tetap manual. Nilai utama proyek ini ada pada disiplin data, risk management, observability, dan evaluasi performa.

Alur utama:

```text
ingest -> validate -> features -> score -> risk -> backtest/gate -> report -> notify -> monitor -> reconcile
```

Jika final signal kosong, jangan langsung anggap error. Sering kali itu berarti sistem sengaja no-trade karena score, event-risk, regime, kill switch, data quality, atau promotion gate.

## Catatan Penting

Saat dokumen ini dibuat, `Dockerfile` memakai command:

```text
python -m src.cli ... serve-web
```

Namun parser di `src/cli.py` tidak mendefinisikan command `serve-web`. Untuk menjalankan dashboard langsung, gunakan:

```powershell
python -m src.web.server --host 127.0.0.1 --port 8080
```
