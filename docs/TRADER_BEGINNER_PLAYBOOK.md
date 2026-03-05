# Trader Beginner Playbook (Minim Loss & Minim Error)

## Tujuan

Panduan operasional sederhana untuk trader baru agar:

- tidak overtrade,
- tidak melanggar stop,
- mengurangi loss besar akibat keputusan emosional.

## Rule Inti

1. Trade hanya jika sistem memberi `TRADE_OK`.
2. Maksimal 1 posisi aktif (profile beginner).
3. Risiko per trade kecil (`0.35%` di profile beginner).
4. Wajib pasang stop-loss saat entry.
5. Jika status `NO_TRADE`, tidak boleh dipaksakan.

## Command Harian

```powershell
powershell -ExecutionPolicy Bypass -File scripts/trade_gate_beginner.ps1 -DebugReasons
```

## Kapan Boleh Entry

Hanya jika output menunjukkan:

- `status = SUCCESS`
- `trade_ready = True`
- `allowed_modes` berisi `swing`
- `decision = TRADE_OK`
- `vol_regime` = `calm` atau `normal`

Jika salah satu gagal, hasilnya `NO_TRADE`.

## Checklist Sebelum Klik Buy

1. Harga belum lari jauh dari `entry`.
2. `stop` dan `tp1/tp2` sudah dihitung sistem.
3. Ukuran posisi (`size`) sesuai output.
4. Tidak ada berita/event-risk mendadak.
5. Total posisi aktif tidak lebih dari 1.

## Checklist Setelah Entry

1. Jangan geser stop-loss ke bawah.
2. Jangan tambah size jika belum ada sinyal baru.
3. Catat jurnal singkat:
   - ticker, alasan entry, hasil akhir (R).

## Rule Saat Rugi Beruntun

Jika rugi 3 trade beruntun:

1. Hentikan entry baru 1-2 hari.
2. Jalankan hanya paper mode.
3. Review `reports/signal_funnel_live.json` dan `reports/backtest_metrics.json`.

## Mindset

- Tujuan awal bukan profit maksimum.
- Tujuan awal adalah konsistensi proses dan proteksi modal.
- Profit mengikuti disiplin, bukan sebaliknya.
