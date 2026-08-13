# Oranix otomatik güncelleme

Kurulum, `ORANIX_UPDATE_MANIFEST_URL` ortam değişkeninde HTTPS adresi varsa açılışta arka planda sürüm kontrolü yapar. Manifest şu alanları içermelidir:

```json
{
  "version": "18001.0",
  "download": "https://ornek-adres/OranixPro-Setup.exe",
  "sha256": "indirilen-kurulumun-64-karakter-sha256-ozeti",
  "notes": "Değişiklik özeti"
}
```

Uygulama güncelleme adresi yoksa normal şekilde çalışır. Manifest ve indirme adresi HTTPS olmak zorundadır. Kurulum dosyası indirilmeden önce SHA256 özeti doğrulanır; eşleşmezse çalıştırılmaz.

GitHub Releases kullanılıyorsa manifest dosyasını sabit bir raw HTTPS adresinde tutup `download` alanına ilgili release asset adresini yazabilirsin.
