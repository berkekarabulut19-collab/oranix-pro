@echo off
chcp 65001 >nul
title ORANİX PRO — AI İddaa Tahmin Analizi
cd /d "C:\Users\Berke\Desktop\IddaaTahminPro"

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║    ORANİX PRO — AI İddaa Tahmin Analizi v2.0        ║
echo  ║    Poisson xG  •  EV Analizi  •  Kelly Kriteri      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  Maçlar ve analizler yükleniyor...
echo.

python app.py

if errorlevel 1 (
    echo.
    echo  [HATA] Uygulama başlatılamadı. Hata detayları yukarıda.
    pause
)
