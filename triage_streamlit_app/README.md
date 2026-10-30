# Instrumen Triage Infeksi Odontogenik

Aplikasi Streamlit ini memindahkan Form A dan Form B dari instrumen penelitian ke entri daring dengan satu baris per episode. Aplikasi menghitung MAP, kelengkapan domain, skor inti, airway override, dan luaran 24 jam secara otomatis. Nilai yang tidak dapat dinilai disimpan sebagai nilai kosong/`NA`, bukan kode 9.

## Fitur

- Form A kontak pertama dengan SBP dan DBP lengkap.
- Enam domain berkode 0, 1, atau `NA`.
- Validasi silent: skor dihitung dan disimpan, tetapi tidak ditampilkan di Form A.
- Form B untuk luaran 24 jam, transfer, luaran sekunder, dan adjudikasi.
- Rekap, filter, ekspor CSV analysis-ready, kamus variabel, dan ringkasan missingness.
- SQLite untuk uji lokal dan PostgreSQL untuk deployment persisten.
- Proteksi kata sandi opsional melalui Streamlit Secrets.

## Menjalankan secara lokal

Gunakan Python 3.12 atau versi Python yang masih didukung oleh Streamlit.

```bash
cd triage_streamlit_app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tanpa `DATABASE_URL`, aplikasi membuat `triage_research.db` di folder aplikasi. File ini sudah dikecualikan dari Git.

## Deployment ke Streamlit Community Cloud

1. Jadikan isi folder `triage_streamlit_app` sebagai root repositori GitHub privat.
2. Di Streamlit Community Cloud, pilih repositori tersebut dan gunakan `app.py` sebagai entrypoint.
3. Buka **Advanced settings > Secrets** dan salin format dari `.streamlit/secrets.toml.example`.
4. Isi `APP_PASSWORD` atau `APP_PASSWORD_SHA256` dan `DATABASE_URL` PostgreSQL.
5. Deploy, lalu uji satu episode dummy dari Form A sampai ekspor CSV sebelum rekrutmen dimulai.

Jika aplikasi ditempatkan di subfolder repositori yang lebih besar, entrypoint dapat diarahkan ke subfolder tersebut, tetapi `.streamlit/config.toml` perlu dipindahkan ke root repositori.

Dokumentasi Streamlit menjelaskan bahwa penyimpanan file lokal pada Community Cloud tidak dijamin persisten. Karena itu, SQLite hanya untuk penggunaan lokal; deployment penelitian harus memakai basis data eksternal yang disetujui institusi. Lihat [Connecting to data](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data), [deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), dan [Secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Format Secrets

```toml
APP_PASSWORD = "kata-sandi-kuat"
DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
```

Untuk menyimpan hash dan bukan kata sandi plaintext:

```bash
python -c "import hashlib, getpass; print(hashlib.sha256(getpass.getpass().encode()).hexdigest())"
```

Simpan hasilnya sebagai `APP_PASSWORD_SHA256` dan jangan isi `APP_PASSWORD`.

## Membaca data di R

```r
dat <- readr::read_csv(
  "triage_analysis_ready_YYYY-MM-DD.csv",
  na = c("", "NA")
)
```

Template pemeriksaan tersedia di `r/import_and_check.R`:

```bash
Rscript r/import_and_check.R triage_analysis_ready_YYYY-MM-DD.csv
```

## Aturan metodologis yang dikunci dalam aplikasi

- `map = (sbp + 2*dbp)/3`.
- `rf_score` hanya dihitung bila semua enam domain tersedia.
- `rf_airway` disimpan sebagai critical override terpisah.
- Site adalah strata evaluasi, bukan komponen skor.
- Transfer saja bukan luaran primer.
- Bila penelusuran tidak lengkap dan tidak ada komponen luaran terkonfirmasi, `outcome24` tetap `NA`.
- Bila keputusan adjudikasi final tersedia, keputusan tersebut menjadi `outcome24`; nilai turunan awal tetap tersedia sebagai `outcome24_raw`.

## Keamanan dan tata kelola

Aplikasi sengaja tidak menyediakan kolom nama, nomor rekam medis, alamat, atau nomor telepon pasien. Tetap gunakan ID studi pseudonim, akses privat, kata sandi kuat, koneksi TLS, backup berkala, dan layanan basis data yang disetujui institusi serta komite etik. Kata sandi tunggal adalah perlindungan dasar, bukan pengganti kontrol akses institusional.

## Pengujian

```bash
cd triage_streamlit_app
python -m unittest discover -s tests -v
```
