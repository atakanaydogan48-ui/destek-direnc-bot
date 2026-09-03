# destek-direnc-bot

TradingView'dan (tvDatafeed uzerinden) Gold (XAUUSD), Silver (XAGUSD), Copper,
Palladium ve Platinum icin saatlik (1h) mum verisi ceker; swing high/low
noktalarindan yatay destek/direnc seviyelerini otomatik tespit eder ve
guncel fiyata en yakin, en cok test edilmis 3-4 destek ile 3-4 direnc
seviyesini mum grafigi uzerinde PNG olarak kaydeder.

## Kurulum

```bash
pip install -r requirements.txt
```

`tvDatafeed`, PyPI'de olmadigi icin dogrudan GitHub'dan kurulur
(`requirements.txt` icinde tanimli).

## Kullanim

```bash
python destek_direnc_bot.py
```

Secenekler:

```bash
python destek_direnc_bot.py --n-bars 300 --outdir output
python destek_direnc_bot.py --username TV_KULLANICI --password TV_SIFRE
python destek_direnc_bot.py --symbols "Gold (XAUUSD)" "Silver (XAGUSD)"
```

- `--username` / `--password` verilmezse (veya `TV_USERNAME` / `TV_PASSWORD`
  ortam degiskenleri set edilmemisse) tvDatafeed anonim oturumla calisir.
- Her sembol icin `output/` klasorune `SEMBOL_1h_TARIH.png` adinda bir
  grafik kaydedilir.

## Yontem

1. Her enstruman icin son 250-300 saatlik mum tvDatafeed ile cekilir
   (OANDA CFD verisi: XAUUSD, XAGUSD, XCUUSD, XPDUSD, XPTUSD).
2. Fraktal yontemle swing high/low noktalari bulunur (bir bar, solundaki ve
   sagindaki N bardan daha yuksek/dusuk ise swing noktasi sayilir).
3. Birbirine yakin (varsayilan %0.15 tolerans icinde) swing fiyatlari tek
   bir yatay seviyede gruplanir; bir seviyeye kac swing noktasi dahil oldugu
   o seviyenin "test sayisi" (touches) olarak alinir.
4. Guncel fiyatin altindaki/ustundeki seviyeler arasindan once fiyata makul
   yakinlikta olanlar secilir, sonra en cok test edilenden aza dogru
   siralanarak en fazla 4 destek ve 4 direnc seviyesi secilir.
5. Sonuc, mum grafigi uzerine kesikli yatay cizgiler ve fiyat/etiketlerle
   birlikte PNG olarak kaydedilir.
