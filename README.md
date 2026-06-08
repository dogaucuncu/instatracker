<div align="center">

# 📊 InstaTracker

**Instagram takipçi değişikliklerini gerçek zamanlı takip eden, yerel çalışan açık kaynak araç.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## 🌟 Özellikler

| Özellik | Açıklama |
|---|---|
| 👋 **Takipten Çıkanlar** | Sizi takipten çıkan kullanıcıları anında tespit eder |
| 🚫 **Engelleyenler** | Sizi engelleyen hesapları listeler |
| ⛔ **Hesap Kapatanlar** | Devre dışı bırakılan / silinen hesapları gösterir |
| ⚠️ **Hâlâ Takip Ettiklerim** | Sizi takipten çıkmasına rağmen hâlâ takip ettiğiniz kişiler |
| 🆕 **Yeni Takipçiler** | Son taramada gelen yeni takipçiler |
| 🕐 **Tarama Geçmişi** | Tüm geçmiş taramaların detaylı özeti |
| 🔄 **Karşılaştırmalı Analiz** | Her taramada önceki snapshot ile karşılaştırma |
| 🔒 **Tam Yerel** | Hiçbir veri dış sunucuya gönderilmez |

---

## 🚀 Kurulum

### Gereksinimler

- **Python 3.10+** → [python.org](https://python.org/downloads)
- **pip** (Python ile birlikte gelir)

### Windows — Tek Tıkla Başlat

```
start.bat dosyasına çift tıklayın.
```

`start.bat` otomatik olarak:
1. Python 3.10'u kontrol eder
2. Gerekli tüm kütüphaneleri yükler
3. Sunucuyu başlatır ve tarayıcıyı açar

### Manuel Kurulum (Linux / macOS / Windows)

```bash
# 1. Repoyu klonla
git clone https://github.com/KULLANICI_ADINIZ/instatracker.git
cd instatracker

# 2. Sanal ortam oluştur (önerilen)
python -m venv venv

# Linux/macOS:
source venv/bin/activate

# Windows:
venv\Scripts\activate

# 3. Bağımlılıkları yükle
pip install -r backend/requirements.txt

# 4. Sunucuyu başlat
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 5. Tarayıcıda aç
# http://localhost:8000
```

---

## 📖 Kullanım

### Web Arayüzü (Önerilen)

1. **Giriş Yap** — Instagram kullanıcı adı ve şifreni gir
   - 2FA (SMS / TOTP / Cihaz Onayı) tam desteklenir
   - Şifre hiçbir yerde saklanmaz

2. **İlk Tarama** — "Şimdi Tara" butonuna bas
   - Mevcut takipçi listeniz kaydedilir (baseline)
   - İlk taramada karşılaştırma yapılmaz

3. **Sonraki Taramalar** — Dilediğinde tekrar tara
   - Önceki snapshot ile karşılaştırılır
   - Takipten çıkanlar, yeni gelenler tespit edilir

4. **Aksiyon Al** — "Hâlâ Takip Ediyorsunuz" rozeti olanları tek tıkla takipten çıkar

### Terminal (CLI) Kullanımı

```bash
cd backend

# Giriş yap
python cli.py login

# Tarama yap
python cli.py scan

# Takipten çıkanları listele
python cli.py unfollowers

# Engelleyenleri listele
python cli.py blockers

# Hesap kapatanları listele
python cli.py deactivated

# İstatistikleri göster
python cli.py stats

# Belirli bir kullanıcıyı takipten çık
python cli.py unfollow <kullanici_adi>

# Çıkış yap
python cli.py logout
```

---

## 🏗️ Proje Yapısı

```
instatracker/
├── backend/
│   ├── main.py                  # FastAPI uygulama giriş noktası
│   ├── config.py                # Yapılandırma sabitleri
│   ├── database.py              # SQLite veri katmanı
│   ├── models.py                # Pydantic modelleri
│   ├── cli.py                   # Komut satırı arayüzü
│   ├── requirements.txt         # Python bağımlılıkları
│   ├── routes/
│   │   ├── auth.py              # Giriş / 2FA / çıkış endpoint'leri
│   │   ├── tracker.py           # Tarama endpoint'leri
│   │   └── dashboard.py         # İstatistik endpoint'leri
│   └── services/
│       ├── instagram_service.py # Instagram API iletişimi (instagrapi)
│       └── tracker_service.py   # Karşılaştırma & olay tespiti
├── frontend/
│   ├── index.html               # Tek sayfa uygulama
│   ├── css/                     # Stiller
│   └── js/
│       ├── app.js               # Ana uygulama mantığı
│       ├── api.js               # Backend API istemcisi
│       └── charts.js            # Grafik bileşenleri
├── data/                        # Çalışma zamanı verisi (git'e eklenmez)
│   ├── instatracker.db          # SQLite veritabanı
│   └── session.json             # Instagram oturum dosyası
├── start.bat                    # Windows tek tıkla başlatıcı
└── README.md
```

---

## 🛠️ Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| **Backend** | Python 3.10+, FastAPI, Uvicorn |
| **Instagram API** | [instagrapi](https://github.com/subzeroid/instagrapi) (gayri resmi) |
| **Veritabanı** | SQLite (WAL modu, yerel) |
| **Frontend** | Vanilla HTML / CSS / JavaScript |
| **CLI** | Click + Rich |

---

## 🔒 Gizlilik & Güvenlik

- ✅ Tüm veriler **yalnızca kendi bilgisayarınızda** saklanır
- ✅ Şifreniz hiçbir zaman veritabanına yazılmaz
- ✅ Instagram oturumu `data/session.json` dosyasında yerel olarak tutulur
- ✅ İstekler arasında **3–7 saniye** rastgele bekleme ile bot tespiti azaltılır
- ✅ v1 API öncelikli, GraphQL yedek stratejisi ile güvenilir veri çekme

> **`data/` klasörü `.gitignore`'a eklenmiştir.** Oturum bilgileriniz ve takipçi verileriniz asla GitHub'a yüklenmez.

---

## ⚠️ Yasal Uyarı

Bu uygulama, Instagram'ın **resmi API'sini değil**, üçüncü taraf bir kütüphane olan [`instagrapi`](https://github.com/subzeroid/instagrapi)'yi kullanmaktadır.

- Instagram'ın [Kullanım Koşulları](https://help.instagram.com/581066165581870)'na aykırı olabilir.
- Yoğun kullanımda hesabınız **geçici kısıtlama veya kalıcı ban** yiyebilir.
- Bu yazılımı kullanarak doğabilecek tüm riskleri kendiniz kabul etmiş olursunuz.
- Geliştirici herhangi bir sorumluluk kabul etmemektedir.

---

## 🤝 Katkıda Bulunma

Pull request'ler memnuniyetle karşılanır!

1. Bu repoyu fork'layın
2. Yeni bir branch oluşturun (`git checkout -b feature/yeni-ozellik`)
3. Değişikliklerinizi commit edin (`git commit -m 'feat: yeni özellik eklendi'`)
4. Branch'inizi push edin (`git push origin feature/yeni-ozellik`)
5. Pull Request açın

---

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) altında dağıtılmaktadır.

---

<div align="center">
  <sub>⭐ Projeyi beğendiyseniz yıldız vermeyi unutmayın!</sub>
</div>
