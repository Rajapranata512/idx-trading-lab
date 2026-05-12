# Penjelasan Proyek Lengkap: IDX Trading Lab

## 1. Gambaran Umum

**IDX Trading Lab** adalah proyek riset dan operasional trading berbasis data untuk saham-saham Indonesia, khususnya universe seperti `LQ45` dan `IDX30`. Tujuan utama proyek ini adalah membangun sebuah pipeline yang mampu:

- mengambil data pasar secara otomatis,
- memvalidasi kualitas data,
- menghitung fitur analitis,
- menghasilkan kandidat saham berdasarkan strategi,
- menerapkan lapisan manajemen risiko yang ketat,
- menyusun laporan yang mudah dibaca,
- menyediakan dashboard web untuk monitoring,
- serta mendukung evaluasi performa strategi secara berkelanjutan.

Secara sederhana, proyek ini bekerja dengan alur:

`ingest -> validate -> features -> score -> risk -> report -> notify -> monitor`

Proyek ini **bukan** sistem broker execution otomatis. Sistem tidak mengeksekusi order langsung ke broker. Sebaliknya, sistem berperan sebagai **mesin riset, penyaring sinyal, dan pendukung keputusan** agar trader dapat mengeksekusi order secara manual dengan disiplin yang lebih tinggi.

## 2. Tujuan Utama Proyek

Dari sisi bisnis dan operasional, proyek ini dibangun untuk menjawab beberapa kebutuhan utama:

1. Mengurangi keputusan trading yang terlalu subjektif.
2. Menyediakan shortlist saham yang lebih terukur dan konsisten.
3. Menekan risiko entry pada kondisi pasar yang buruk.
4. Menyediakan evaluasi performa strategi secara historis dan out-of-sample.
5. Menurunkan kemungkinan error operasional melalui otomasi pipeline dan dashboard monitoring.

Dengan kata lain, proyek ini tidak hanya mengejar profit, tetapi juga berusaha membangun **proses trading yang disiplin, dapat diaudit, dan lebih aman**.

## 3. Masalah yang Ingin Diselesaikan

Dalam praktik trading harian, terdapat beberapa masalah umum:

- data harga tidak selalu siap atau konsisten,
- keputusan entry sering dipengaruhi emosi,
- performa strategi terlihat bagus di masa lalu tetapi gagal saat kondisi pasar berubah,
- trader kesulitan membedakan antara no-trade yang sehat dan error sistem,
- hasil eksekusi riil sering berbeda dari rencana di backtest,
- kualitas model prediktif sering tidak terukur secara jujur.

IDX Trading Lab mencoba menyelesaikan masalah ini melalui kombinasi:

- rule-based scoring,
- validasi historis,
- walk-forward out-of-sample,
- risk gate,
- dashboard operasional,
- paper-trading loop,
- dan model machine learning bayangan (`model_v2`) yang diuji sebelum dipertimbangkan untuk produksi.

## 4. Cakupan Fungsional Proyek

Secara fungsional, proyek ini memiliki beberapa blok utama:

1. **Ingestion data**
   Mengambil data pasar harian dan intraday dari provider yang tersedia.

2. **Validasi kualitas data**
   Memastikan data tidak stale, tidak duplikat, tidak missing, dan masih layak dipakai.

3. **Feature engineering**
   Mengubah data OHLCV menjadi indikator, statistik momentum, volatilitas, liquidity proxy, dan context pasar.

4. **Strategy scoring**
   Menghasilkan ranking kandidat saham untuk mode strategi seperti `T+1` dan `Swing`.

5. **Risk engine**
   Menentukan apakah sinyal boleh dipakai atau harus diblokir karena kondisi pasar, event risk, drawdown, atau guardrail lain.

6. **Backtest dan walk-forward**
   Mengukur performa strategi secara historis dan out-of-sample.

7. **Model V2 / shadow model**
   Menambah lapisan machine learning yang berjalan paralel untuk evaluasi, tanpa langsung override keputusan live.

8. **Paper trading dan live reconciliation**
   Membandingkan rencana sinyal dengan simulasi atau hasil fill nyata.

9. **Reporting dan dashboard web**
   Menyajikan hasil pipeline dalam bentuk JSON, CSV, HTML, markdown, dan UI web.

## 5. Struktur Direktori dan Perannya

Berikut penjelasan folder penting di dalam repo:

### 5.1 `src/`

Ini adalah inti kode aplikasi. Beberapa modul penting:

- `src/ingest`
  Menangani pengambilan data harga dari provider, termasuk fallback dan validasi awal.

- `src/features`
  Menghitung fitur turunan dari data pasar, seperti return, moving average, ATR, volatility, market breadth, dan context market lainnya.

- `src/strategy`
  Menangani logika penilaian kandidat saham untuk mode strategi seperti `t1`, `swing`, dan intraday.

- `src/risk`
  Menangani sizing, event-risk, volatility recalibration, serta kontrol risiko lainnya.

- `src/backtest`
  Menjalankan simulasi historis dan walk-forward validation untuk mengukur kualitas strategi.

- `src/model_v2`
  Menangani training, inference, shadow scoring, calibration, labeling, dan promotion logic untuk model machine learning generasi kedua.

- `src/report`
  Menyusun output seperti laporan harian, weekly KPI, live reconciliation, dan coaching note.

- `src/web`
  Menyediakan service layer dan server untuk dashboard web interaktif.

- `src/paper_trading`
  Menghasilkan simulasi paper fills yang lebih realistis berdasarkan snapshot sinyal historis.

- `src/analytics`
  Menyediakan analisis tambahan seperti audit edge `swing` berdasarkan regime, grup, dan volatilitas.

- `src/runtime`
  Menyimpan kebijakan runtime seperti mode aktif dan regime policy yang dipakai lintas pipeline.

- `src/intraday`
  Menangani pipeline data dan scoring untuk mode intraday.

- `src/universe`
  Menangani pembaruan universe saham yang dipakai sistem.

- `src/notify`
  Mengirim notifikasi, misalnya via Telegram.

- `src/utils`
  Menyediakan helper IO dan logging.

### 5.2 `config/`

Folder ini menyimpan konfigurasi runtime utama, terutama `config/settings.json`.

Konfigurasi mencakup:

- data provider,
- event-risk,
- risk sizing,
- regime threshold,
- validation setting,
- model_v2,
- paper trading,
- risk budget,
- rollout mode.

Schema konfigurasinya divalidasi melalui `src/config.py`.

### 5.3 `data/`

Folder ini menyimpan data mentah, data referensi, dan data hasil proses.

Contohnya:

- `data/raw/prices_daily.csv`
- `data/raw/prices_intraday.csv`
- `data/reference/universe_lq45_idx30.csv`
- `data/reference/event_risk_blacklist.csv`
- `data/processed/features.parquet`

### 5.4 `reports/`

Semua hasil pipeline harian dan metrik evaluasi biasanya bermuara ke sini. Contoh:

- `daily_signal.json`
- `daily_report.html`
- `execution_plan.csv`
- `backtest_metrics.json`
- `walk_forward_metrics.json`
- `model_v2_shadow_signals.json`
- `weekly_kpi.json`
- `live_reconciliation.json`
- `paper_fills_summary.json`
- `swing_audit.json`
- `run_log_YYYYMMDD.json`

### 5.5 `web/`

Berisi asset front-end seperti HTML, CSS, dan JavaScript untuk dashboard web.

### 5.6 `docs/`

Berisi panduan operasional, blueprint model, playbook trader pemula, runbook n8n, dan dokumen pendukung lainnya.

## 6. Alur Kerja End-to-End

Secara end-to-end, pipeline proyek ini dapat dipahami sebagai berikut:

### Tahap 1: Pengambilan Data

Sistem mengambil data harga dari provider utama. Bila provider utama gagal, sistem dapat memakai fallback chain sesuai konfigurasi. Data yang diambil minimal berisi:

- `date`
- `ticker`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `source`
- `ingested_at`

Untuk mode harian, data ini menjadi fondasi seluruh proses berikutnya.

### Tahap 2: Validasi Kualitas Data

Sebelum data dipakai, sistem memeriksa beberapa hal:

- apakah data stale,
- apakah ada missing rows,
- apakah ada duplikasi,
- apakah ada ticker yang hilang,
- apakah ada outlier ekstrem.

Jika data tidak lolos kualitas minimum, pipeline dapat menghentikan proses dan menandai run sebagai failure, karena keputusan trading berbasis data buruk sangat berisiko.

### Tahap 3: Perhitungan Fitur

Data harga mentah kemudian diubah menjadi fitur-fitur analitis, misalnya:

- return 1 hari, 5 hari, 20 hari,
- moving average,
- ATR,
- volatility,
- rata-rata volume,
- liquidity proxy,
- jarak terhadap high/low periode tertentu,
- breadth pasar,
- rata-rata return pasar,
- median ATR pasar,
- relative return terhadap universe.

Tujuan tahap ini adalah mengubah data harga mentah menjadi informasi yang lebih bermakna untuk scoring maupun machine learning.

### Tahap 4: Scoring Strategi

Setelah fitur tersedia, sistem menilai kandidat saham berdasarkan mode strategi.

Mode yang dikenal di proyek ini:

- `t1`: orientasi jangka sangat pendek
- `swing`: orientasi hold beberapa hari sampai beberapa minggu
- intraday: pipeline terpisah untuk siklus lebih pendek

Pada praktiknya, proyek saat ini bergerak ke arah **swing-priority** karena mode `swing` lebih menjanjikan dibanding `t1`.

### Tahap 5: Risk Filtering dan Gating

Nilai skor saja tidak cukup. Kandidat yang tampak bagus tetap bisa dibatalkan oleh lapisan risiko, seperti:

- **regime filter**: memeriksa kondisi pasar sedang sehat atau tidak,
- **event-risk filter**: memblokir saham yang dekat dengan event berisiko,
- **kill switch**: menghentikan mode yang performanya menurun,
- **promotion gate**: memastikan model/strategi belum dipakai live sebelum lolos syarat,
- **quality gate**: memastikan data dan pipeline tidak bermasalah,
- **risk budget**: membatasi eksposur sesuai fase rollout.

Hasil akhirnya bukan sekadar “saham bagus”, melainkan “apakah saham ini **layak** dipertimbangkan dalam kondisi sekarang”.

### Tahap 6: Penyusunan Laporan dan Output

Setelah seluruh filter dijalankan, sistem menghasilkan:

- kandidat teratas,
- level entry,
- stop-loss,
- TP1 dan TP2,
- ukuran posisi,
- HTML report,
- JSON signal,
- log run,
- ringkasan KPI dan status risiko.

### Tahap 7: Monitoring, Paper Trading, dan Evaluasi

Sinyal yang dihasilkan kemudian bisa:

- direview di dashboard,
- dipakai untuk paper trading,
- dibandingkan dengan fill broker nyata,
- dijadikan bahan evaluasi mingguan atau bulanan.

## 7. Penjelasan Strategi yang Digunakan

### 7.1 Mode `T+1`

Mode ini dirancang untuk horizon sangat pendek. Namun, dari dokumentasi dan status konfigurasi, mode ini saat ini tidak menjadi prioritas utama. Dalam konfigurasi live yang defensif, `min_live_score_t1` pernah diset sangat tinggi sehingga praktis dibekukan.

Makna pentingnya:

- proyek masih mendukung mode `t1`,
- tetapi keputusan operasional cenderung menghindarinya,
- fokus saat ini lebih diarahkan ke strategi `swing`.

### 7.2 Mode `Swing`

Mode `swing` adalah inti strategi yang paling relevan untuk proyek saat ini. Horizon umumnya beberapa hari sampai beberapa minggu, dengan tujuan memilih saham yang:

- memiliki struktur tren yang sehat,
- menunjukkan momentum relatif baik,
- tidak terlalu berisiko dari sisi volatilitas,
- memiliki konfirmasi volume atau context pasar yang memadai.

Strategi `swing` ini lebih sesuai dengan kondisi trader yang ingin lebih selektif, tidak terlalu overtrade, dan masih menjaga ruang bagi risk management.

## 8. Backtest dan Walk-Forward Validation

Salah satu kekuatan proyek ini adalah tidak hanya mengandalkan hasil “in-sample”, tetapi juga melakukan **walk-forward validation**.

### 8.1 Backtest

Backtest dipakai untuk melihat bagaimana strategi akan tampil bila diterapkan pada data historis. Metrik utama biasanya meliputi:

- `WinRate`
- `ProfitFactor`
- `Expectancy`
- `Trades`
- `CAGR`
- `MaxDD`

### 8.2 Walk-Forward

Walk-forward membagi data menjadi beberapa fold berdasarkan waktu:

- train period,
- test period,
- step period.

Dengan pendekatan ini, proyek tidak hanya menilai “strategi ini bagus di masa lalu”, tetapi juga “apakah strategi masih bekerja pada data out-of-sample yang lebih mirip kondisi real”.

Ini sangat penting untuk mengurangi overfitting.

### 8.3 Makna Praktis

Jika performa hanya bagus di satu fold tetapi hancur di fold lain, strategi belum layak dianggap stabil. Karena itu, proyek ini memakai gate lanjutan seperti:

- jumlah trade OOS minimum,
- profit factor minimum,
- expectancy harus positif,
- drawdown maksimum,
- stabilitas antar fold.

## 9. Machine Learning dan `model_v2`

Proyek ini sudah memiliki fondasi machine learning dalam bentuk `model_v2`.

### 9.1 Tujuan `model_v2`

`model_v2` dirancang untuk:

- meningkatkan kualitas sinyal,
- menurunkan noise,
- menghasilkan probabilitas keberhasilan (`p_win`),
- memperkirakan `expected_r`,
- membantu kalibrasi keputusan trading,
- tetapi tetap tunduk pada risk engine yang sama.

### 9.2 Pendekatan yang Dipakai

`model_v2` saat ini berada dalam pendekatan **shadow mode**. Artinya:

- model berjalan,
- output-nya dicatat,
- dibandingkan dengan scorer utama,
- tetapi belum langsung override keputusan produksi.

Pendekatan ini sehat karena memberi ruang evaluasi tanpa mengambil risiko terlalu cepat.

### 9.3 Komponen Model V2

Modul `src/model_v2` mencakup:

- `train.py`: training model
- `predict.py`: inference harian
- `shadow.py`: output shadow dan A/B comparison
- `calibration.py`: kalibrasi probabilitas
- `labeling.py`: penyusunan target/label
- `promotion.py`: logic promosi model
- `io.py`: simpan dan load artifact model

### 9.4 Prinsip Penting

Dalam blueprint proyek, model AI tidak diposisikan sebagai pengganti total risk engine. Model tetap harus melewati:

- regime filter,
- kill switch,
- event-risk,
- quality gate,
- dan promotion rule.

Jadi machine learning di proyek ini diposisikan sebagai **lapisan tambahan untuk meningkatkan kualitas keputusan**, bukan sebagai mesin “black box” yang bebas mengambil keputusan sendiri.

## 10. Risk Engine

Lapisan risiko adalah salah satu bagian paling penting dari proyek ini.

### 10.1 Regime Filter

Regime filter memeriksa apakah kondisi pasar mendukung trading atau tidak. Indikator yang biasa dipakai meliputi:

- breadth di atas MA tertentu,
- rata-rata return pasar,
- median ATR pasar.

Jika kondisi pasar dinilai buruk, status bisa menjadi `risk_off`, dan sistem memblokir sinyal live.

### 10.2 Event-Risk Filter

Saham yang dekat dengan event seperti suspend, UMA, atau material event dapat dikeluarkan dari daftar kandidat. Tujuannya untuk menghindari risiko diskontinuitas harga yang tidak tertangkap indikator teknikal biasa.

### 10.3 Kill Switch

Kill switch menjaga sistem agar berhenti bila performa rolling sebuah mode memburuk, misalnya:

- profit factor rolling turun,
- expectancy rolling negatif,
- jumlah trade tertentu sudah cukup untuk menilai penurunan performa.

### 10.4 Risk Budget dan Position Sizing

Proyek juga mengatur:

- risk per trade,
- daily loss stop,
- weekly stop,
- batas jumlah posisi,
- cap eksposur sektor,
- serta pengaruh volatilitas pasar terhadap ukuran posisi.

Dengan demikian, sistem tidak hanya memilih saham, tetapi juga mengatur **seberapa besar risiko** yang pantas diambil.

## 11. Paper Trading dan Live Reconciliation

Proyek ini tidak berhenti pada backtest. Ada dua lapisan lanjutan:

### 11.1 Paper Trading

Melalui `src/paper_trading/auto_fill.py`, sistem dapat membuat paper fills realistis dari snapshot sinyal historis. Ini membantu menjawab pertanyaan:

- jika sinyal ini dieksekusi secara disiplin, apa hasil simulasinya?
- apakah perbedaan entry/exit realistis mengubah performa?

### 11.2 Live Reconciliation

Dengan `src/report/live_reconciliation.py`, sistem membandingkan:

- snapshot sinyal dari pipeline,
- dengan fill broker nyata yang diekspor manual.

Tujuannya adalah mengukur:

- entry match rate,
- signal execution rate,
- slippage,
- fee riil,
- realized expectancy,
- profit factor riil.

Ini sangat penting karena strategi yang terlihat bagus di backtest bisa tetap gagal di dunia nyata akibat biaya, disiplin eksekusi, atau keterlambatan entry.

## 12. Dashboard Web

Dashboard web adalah lapisan antarmuka proyek yang memudahkan monitoring sistem.

Kemampuan utamanya mencakup:

- melihat status pipeline terbaru,
- memeriksa sinyal aktif,
- melihat hasil guardrail,
- melihat recent runs,
- menjalankan `run-daily` dari UI,
- memonitor job asinkron,
- melihat status warning/failure secara lebih mudah,
- melihat audit swing, paper fills, dan status model bayangan.

Peran dashboard ini bukan hanya kosmetik. Dashboard adalah **alat observabilitas** supaya pengguna dapat:

- tahu apakah sistem sehat,
- tahu apakah no-trade adalah keputusan risiko yang normal,
- tahu apakah ada failure operasional,
- tahu alasan mengapa sinyal diblokir.

## 13. Output dan Deliverables Sistem

Beberapa output penting dari proyek ini:

- `reports/daily_report.html`
- `reports/daily_signal.json`
- `reports/execution_plan.csv`
- `reports/backtest_metrics.json`
- `reports/walk_forward_metrics.json`
- `reports/model_v2_shadow_signals.json`
- `reports/model_v2_ab_test.json`
- `reports/live_reconciliation.json`
- `reports/weekly_kpi.json`
- `reports/paper_fills_summary.json`
- `reports/swing_audit.json`
- `reports/run_log_YYYYMMDD.json`

Setiap file memiliki peran berbeda:

- laporan harian untuk keputusan trading,
- metrik historis untuk validasi strategi,
- KPI untuk monitoring kualitas operasional,
- log run untuk debugging,
- file rekonsiliasi untuk evaluasi eksekusi nyata.

## 14. Cara Menjalankan Sistem

Secara umum, proyek ini dapat dijalankan melalui CLI.

Contoh command utama:

```powershell
python -m src.cli ingest-daily
python -m src.cli compute-features
python -m src.cli score
python -m src.cli backtest
python -m src.cli walk-forward
python -m src.cli paper-fills
python -m src.cli weekly-kpi
python -m src.cli reconcile-live
python -m src.cli run-daily
python -m src.cli serve-web --host 127.0.0.1 --port 8080
```

Untuk operasional harian, perintah yang paling umum adalah:

```powershell
python -m src.cli run-daily
python -m src.cli serve-web --host 127.0.0.1 --port 8080
```

## 15. Kelebihan Proyek

Dari sisi engineering dan riset, proyek ini memiliki beberapa kekuatan utama:

1. **Arsitektur end-to-end**
   Proyek tidak hanya berhenti pada scoring, tetapi mencakup data, risk, laporan, dashboard, dan evaluasi pasca-sinyal.

2. **Risk-first design**
   Sistem lebih mementingkan proteksi modal dibanding memaksakan frekuensi trade.

3. **Ada layer validasi out-of-sample**
   Walk-forward validation membuat evaluasi strategi lebih realistis.

4. **Ada observability**
   Dashboard, log run, KPI, dan reconciliation membantu mengurangi blind spot.

5. **Ada jalur pengembangan AI yang terkontrol**
   `model_v2` berjalan dalam shadow mode, sehingga eksperimen bisa dilakukan tanpa langsung membahayakan sistem live.

## 16. Keterbatasan Proyek

Sebagai sistem riset yang berkembang, proyek ini juga memiliki beberapa keterbatasan:

1. **Kualitas hasil tetap bergantung pada kualitas data provider**
   Jika data stale atau provider gagal, keputusan bisa terganggu.

2. **Tidak ada jaminan profit**
   Backtest yang baik tidak menjamin hasil live akan sama.

3. **Mode tertentu belum tentu stabil**
   Misalnya, mode `t1` dapat menjadi tidak prioritas bila edge-nya melemah.

4. **Machine learning masih membutuhkan validasi ketat**
   Model yang terlihat baik di train belum tentu memberi nilai tambah di live.

5. **Sistem belum sepenuhnya broker-native**
   Eksekusi masih mengandalkan trader untuk memasukkan order manual secara disiplin.

## 17. Posisi Proyek dari Perspektif AI dan Deep Learning

Proyek ini sudah sangat layak menjadi fondasi untuk pengembangan lanjutan seperti:

- machine learning tabular,
- sentiment analysis,
- regime-aware model,
- confidence-based sizing,
- dan pada tahap lebih lanjut, deep learning.

Namun, arah pengembangan yang sehat adalah:

1. memperkuat kualitas data,
2. memperkuat label dan feature engineering,
3. memperkuat evaluasi out-of-sample,
4. memastikan paper/live feedback loop aktif,
5. baru kemudian menambah kompleksitas model.

Dengan pendekatan itu, AI menjadi alat untuk meningkatkan kualitas keputusan, bukan sekadar menambah kompleksitas tanpa edge nyata.

## 18. Posisi Proyek bagi Pengguna

Bagi pengguna, proyek ini berfungsi sebagai:

- **mesin shortlist saham**,
- **mesin validasi kondisi pasar**,
- **alat disiplin trading**,
- **alat monitoring performa sistem**,
- **alat pembelajaran bagi trader baru**,
- dan **fondasi eksperimen model yang lebih maju**.

Artinya, proyek ini bukan hanya aplikasi teknis, tetapi sebuah **framework pengambilan keputusan trading berbasis data dan risk governance**.

## 19. Kesimpulan

Secara keseluruhan, **IDX Trading Lab** adalah proyek trading research dan decision-support yang cukup lengkap. Proyek ini menggabungkan:

- ingestion data,
- quality control,
- feature engineering,
- strategy scoring,
- backtest dan walk-forward,
- risk engine,
- machine learning shadow model,
- paper trading,
- live reconciliation,
- reporting,
- dan dashboard web.

Nilai utama proyek ini bukan sekadar mencari saham yang berpotensi naik, tetapi membangun **proses trading yang lebih sistematis, terukur, defensif, dan dapat diaudit**. Dengan fondasi seperti ini, proyek sangat layak untuk terus dikembangkan ke arah sistem trading berbasis AI yang lebih matang, selama pengembangannya tetap menjaga prinsip utama: **quality-first, risk-first, dan validation-first**.

## 20. Dokumen Pendukung yang Sebaiknya Dibaca Bersama

Untuk memahami proyek ini lebih dalam, dokumen berikut juga relevan:

- `README.md`
- `docs/MODEL_V2_BLUEPRINT.md`
- `docs/SOP_DAILY.md`
- `docs/TRADER_BEGINNER_PLAYBOOK.md`
- `docs/LIVE_RECONCILIATION.md`
- `docs/N8N_LOCAL_SETUP.md`
- `docs/N8N_RUNBOOK.md`

Dokumen ini dimaksudkan sebagai ringkasan penjelasan komprehensif yang menghubungkan seluruh sisi proyek: bisnis, arsitektur, model, risiko, operasional, dan pengembangan lanjutan.
