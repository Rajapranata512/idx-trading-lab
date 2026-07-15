# 00 - Agent Reading Guide

Bagian ini adalah panduan baca untuk agent AI. Tujuannya menghemat token tanpa kehilangan pemahaman penting.

## Mode Resume Setelah Token Reset

Jika agent baru saja reset token atau kehilangan konteks:

1. Jangan membaca semua file project.
2. Jangan scan seluruh `reports/`, `data/`, `web/reports/`, atau log historis.
3. Baca `docs/AI_PROJECT_CONTEXT.md`.
4. Baca file ini.
5. Pilih satu rute tugas di bagian "Cara Memilih Bagian".
6. Baca hanya modul dan test yang terkait langsung dengan permintaan user terbaru.
7. Jika user meminta coding, implementasikan perubahan kecil yang bisa diverifikasi.
8. Jika user meminta analisis, jangan mengedit file kecuali diminta.

Target resume yang benar bukan "paham semua kode", tetapi "cukup paham untuk menyelesaikan tugas terbaru dengan aman".

## Urutan Baca Default

Jika tugas masih umum:

1. Baca `docs/AI_PROJECT_CONTEXT.md`.
2. Baca file ini.
3. Pilih satu bagian lain dari folder `docs/ai-context/`.
4. Baru baca kode atau test yang relevan.

Jika tugas sudah spesifik:

1. Baca file ini.
2. Baca file bagian sesuai area tugas.
3. Baca modul sumber yang tepat.
4. Baca test yang berhubungan.

## Context Budget

Budget kecil:

- `docs/AI_PROJECT_CONTEXT.md`
- file bagian yang relevan saja
- 1-2 file kode utama
- test terdekat

Budget sedang:

- semua di budget kecil
- `README.md`
- `src/config.py`
- `src/cli.py` bagian fungsi yang relevan

Budget besar:

- semua di budget sedang
- dokumen pendukung di `docs/`
- beberapa report/log terbaru jika debugging

Stop membaca jika sudah tahu:

- modul yang akan diubah,
- file output yang terdampak,
- test yang relevan,
- risiko perubahan terhadap sinyal live atau dashboard.

Lanjut membaca hanya jika ada error, kontrak data belum jelas, atau test gagal.

## File Yang Biasanya Tidak Perlu Dibaca Di Awal

Jangan mulai dari file ini karena boros token:

- `web/reports/snapshots/*.json`
- `web/reports/run_log_*.json`
- `reports/*.log`
- `tmp_*.log`
- `data/raw/prices_daily.csv`
- `data/raw/prices_intraday.csv`
- artifact model di `models/`

Gunakan file besar hanya untuk debugging kasus spesifik.

## Cara Memilih Bagian

Jika user bertanya "ini proyek apa":

- Baca `01-project-overview.md`.

Jika user ingin menjalankan pipeline:

- Baca `03-daily-workflow-run-daily.md`.
- Baca `05-operations-and-debugging.md`.

Jika user ingin mengubah config:

- Baca `02-repository-map-and-config.md`.
- Baca `src/config.py`.

Jika user ingin mengubah strategi/risk:

- Baca `04-module-workflows.md`.
- Baca file di `src/strategy/` atau `src/risk/`.
- Baca test terkait.

Jika user ingin debugging no-signal:

- Baca `05-operations-and-debugging.md`.
- Baca `reports/signal_funnel_live.json`.
- Baca `reports/backtest_metrics.json`.

Jika user ingin meningkatkan akurasi/performa sinyal:

- Baca `04-module-workflows.md`.
- Baca `src/analytics/signal_accuracy.py`.
- Baca `src/risk/profit_quality.py`.
- Baca `src/strategy/ranker.py` hanya bila scoring perlu diubah.
- Baca `tests/test_signal_accuracy.py` dan `tests/test_profit_quality.py`.

Jika user ingin refactor atau tambah fitur:

- Baca `06-change-guide-and-tests.md`.
- Baca modul terkait.
- Baca test terkait.

## Aturan Kerja Untuk Agent

Jangan ubah schema output tanpa melacak semua downstream reader.

Jangan melemahkan risk gate kecuali user meminta eksplisit dan dampaknya dijelaskan.

Jangan meningkatkan jumlah sinyal dengan menurunkan threshold tanpa audit expectancy/profit factor.

Jangan push ke GitHub atau deploy kecuali user meminta eksplisit.

Jangan commit secret atau menulis token ke file.

Jangan menghapus report/data historis tanpa instruksi jelas.

Jangan membaca semua file hanya karena ingin "paham semuanya". Proyek ini punya banyak output historis yang tidak perlu untuk kebanyakan tugas.

Jangan melakukan redesign UI, refactor lintas modul, atau perubahan strategi besar jika tugas user hanya meminta dokumentasi, penilaian, atau debugging sempit.

## Pertanyaan Internal Sebelum Coding

Sebelum edit, jawab singkat untuk diri sendiri:

1. Modul apa yang disentuh?
2. Output apa yang berubah?
3. Test apa yang harus dijalankan?
4. Apakah ada risk gate, data contract, atau dashboard contract yang terdampak?
5. Apakah perubahan ini bisa membuat sinyal live berubah?
