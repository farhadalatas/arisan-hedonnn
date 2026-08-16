# Arisan Hedonnn V5 - fondasi akun lokal

Versi ini menambahkan homepage, registrasi, login, dashboard, workspace, dan event yang disimpan dalam database SQLite `arisan-hedonnn.db`. Password di-hash dengan PBKDF2-SHA256, sesi login disimpan sebagai hash token, dan request perubahan dilindungi CSRF, validasi Host/Origin, rate limit, batas ukuran request, CSP, dan security headers.

## Pemakaian lokal

Jalankan `START ARISAN.bat`. Launcher membuka homepage di `http://127.0.0.1:8081/`. Buat akun lokal pertama melalui halaman registrasi. Jika `arisan-live-session.json` lama tersedia, state tersebut diimpor ke acara pertama akun pertama.

Cadangkan file berikut secara berkala:

- `arisan-hedonnn.db`
- `arisan-hedonnn.db-wal` dan `arisan-hedonnn.db-shm` jika ada saat server aktif

Cara paling aman adalah menghentikan server sebelum menyalin database untuk backup.

## Schema database

- `users`: identitas dan password hash.
- `workspaces`: ruang kerja milik pengguna.
- `workspace_members`: relasi pengguna, workspace, dan role.
- `user_sessions`: hash token login, CSRF, dan masa berlaku.
- `events`: acara, state kocokan, live draw, dan pemenang terakhir.
- `schema_migrations`: versi perubahan schema.

## Konfigurasi HTTPS

Atur environment variable berdasarkan `production.env.example`:

- `ARISAN_ENV=production`
- `ARISAN_HOST=127.0.0.1`
- `ARISAN_PORT=8081`
- `ARISAN_SECURE_COOKIE=1`
- `ARISAN_ALLOWED_HOSTS` berisi domain production
- `ARISAN_ALLOWED_ORIGINS` berisi origin HTTPS lengkap

Gunakan reverse proxy HTTPS seperti Caddy atau Nginx. Jangan mengekspos port Python langsung ke internet.

## Rekam layar MP4

Rekaman berjalan di browser, default-nya mati, dan tidak dikirim ke server. Chrome meminta pengguna memilih tab, jendela, atau layar sebelum setiap rekaman. Fitur membutuhkan HTTPS di production atau localhost untuk penggunaan lokal.

## Batasan sebelum SaaS publik

Fondasi ini cocok untuk pengembangan dan pilot lokal, tetapi belum direkomendasikan menerima pelanggan publik berbayar. Sebelum go-live SaaS:

1. Migrasikan SQLite ke PostgreSQL terkelola.
2. Jalankan backend dengan server/framework production-grade.
3. Tambahkan verifikasi email dan reset password.
4. Tambahkan MFA untuk akun sensitif.
5. Gunakan secret manager, monitoring, backup otomatis, staging, dan CI.
6. Lakukan penetration test dan pengujian isolasi tenant independen.
7. Siapkan Privacy Policy, Terms, kebijakan penghapusan data, dan kajian PSE/PDP.
8. Pisahkan layar operator dan viewer publik dengan token akses terbatas.

Jangan mengklaim versi lokal ini sebagai layanan cloud production sebelum pekerjaan di atas selesai.
