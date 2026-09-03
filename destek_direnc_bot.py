#!/usr/bin/env python3
"""
Destek/Direnc Bot
==================

TradingView'dan (tvDatafeed uzerinden) Gold (XAUUSD), Silver (XAGUSD),
Copper, Palladium ve Platinum icin saatlik (1h) mum verisi ceker; swing
high/low noktalarindan yatay destek/direnc seviyelerini tespit eder ve
guncel fiyata en yakin, en cok test edilmis 3-4 destek ile 3-4 direnc
seviyesini mum grafigi uzerinde PNG olarak kaydeder.

Kurulum:
    pip install -r requirements.txt

Kullanim:
    python destek_direnc_bot.py
    python destek_direnc_bot.py --n-bars 300 --outdir output
    python destek_direnc_bot.py --username TV_KULLANICI --password TV_SIFRE

Not: tvDatafeed, TradingView'in resmi olmayan (unofficial) bir istemcisidir.
Kullanici adi/sifre verilmezse anonim oturum ile calisir; bazi semboller
icin oturum acmak veri erisimini iyilestirebilir.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence

import matplotlib

matplotlib.use("Agg")  # headless ortamlarda PNG kaydetmek icin
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------

# (gorunen isim -> (tvDatafeed sembolu, borsa/kaynak))
# Hepsi OANDA CFD verisi kullanir; boylece kaynak tutarli olur ve saatlik
# veri her sembol icin genellikle mevcuttur.
SYMBOLS: dict[str, tuple[str, str]] = {
    "Gold (XAUUSD)": ("XAUUSD", "OANDA"),
    "Silver (XAGUSD)": ("XAGUSD", "OANDA"),
    "Copper (XCUUSD)": ("XCUUSD", "OANDA"),
    "Palladium (XPDUSD)": ("XPDUSD", "OANDA"),
    "Platinum (XPTUSD)": ("XPTUSD", "OANDA"),
}

DEFAULT_N_BARS = 300           # sadece son 250-300 mum kullanilir
SWING_LEFT_RIGHT = 3            # fraktal swing icin sol/sag bar sayisi
CLUSTER_TOLERANCE_PCT = 0.0015  # seviyeleri gruplamak icin fiyat toleransi (%0.15)
MAX_LEVELS_PER_SIDE = 4         # her yonde (destek/direnc) gosterilecek maksimum seviye
MIN_LEVELS_PER_SIDE = 3         # mumkunse gosterilecek minimum seviye
PROXIMITY_BANDS = (0.03, 0.06, 0.10, 0.20, 1.0)  # yakinlik bantlari (fiyatin yuzdesi)


@dataclass
class Level:
    price: float
    touches: int


# --------------------------------------------------------------------------
# Veri cekme
# --------------------------------------------------------------------------

def fetch_hourly_data(tv, symbol: str, exchange: str, n_bars: int) -> pd.DataFrame:
    from tvDatafeed import Interval

    df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_1_hour, n_bars=n_bars)
    if df is None or df.empty:
        raise RuntimeError(f"{exchange}:{symbol} icin veri alinamadi (bos sonuc).")

    df = df.rename(columns={c: c.lower() for c in df.columns})
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"{exchange}:{symbol} verisinde beklenen kolonlar yok: {df.columns.tolist()}")

    df = df[["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])]
    df = df.dropna(subset=["open", "high", "low", "close"])
    # tvDatafeed genelde eskiden yeniye sirali doner; garanti altina al.
    df = df.sort_index()
    return df


# --------------------------------------------------------------------------
# Swing high/low tespiti
# --------------------------------------------------------------------------

def find_swing_points(df: pd.DataFrame, left: int = SWING_LEFT_RIGHT, right: int = SWING_LEFT_RIGHT):
    """Basit fraktal yontemle swing high/low bar indekslerini ve fiyatlarini bulur.

    Bir bar, kendisinden `left` bar once ve `right` bar sonraki tum
    barlardan daha yuksek (swing high) veya daha dusuk (swing low) ise
    swing noktasi olarak isaretlenir.
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)

    swing_high_prices: List[float] = []
    swing_low_prices: List[float] = []

    for i in range(left, n - right):
        window_high = highs[i - left : i + right + 1]
        if highs[i] == window_high.max() and np.argmax(window_high) == left:
            swing_high_prices.append(float(highs[i]))

        window_low = lows[i - left : i + right + 1]
        if lows[i] == window_low.min() and np.argmin(window_low) == left:
            swing_low_prices.append(float(lows[i]))

    return swing_high_prices, swing_low_prices


# --------------------------------------------------------------------------
# Seviyeleri gruplama (clustering) ve secim
# --------------------------------------------------------------------------

def cluster_levels(prices: Sequence[float], tolerance_pct: float = CLUSTER_TOLERANCE_PCT) -> List[Level]:
    """Birbirine yakin fiyat noktalarini tek bir yatay seviyede birlestirir.

    `touches`, o seviyeye kac swing noktasinin dahil oldugunu (ne kadar
    test edildigini) gosterir.
    """
    if not prices:
        return []

    sorted_prices = sorted(prices)
    clusters: List[List[float]] = [[sorted_prices[0]]]

    for price in sorted_prices[1:]:
        cluster_avg = sum(clusters[-1]) / len(clusters[-1])
        if abs(price - cluster_avg) / cluster_avg <= tolerance_pct:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [Level(price=sum(c) / len(c), touches=len(c)) for c in clusters]


def select_levels(levels: Sequence[Level], current_price: float, side: str, max_levels: int) -> List[Level]:
    """Guncel fiyata gore destek/direnc adaylarini secer.

    Once fiyata makul yakinlikta olan adaylari daraltir (yakinlik bandini
    kademeli genisleterek), sonra bu adaylari en cok test edilenden (touch
    sayisi) en aza, esitlikte ise fiyata en yakindan en uzaga siralar.
    """
    if side == "support":
        candidates_all = [lvl for lvl in levels if lvl.price < current_price]
    elif side == "resistance":
        candidates_all = [lvl for lvl in levels if lvl.price > current_price]
    else:
        raise ValueError("side 'support' ya da 'resistance' olmali")

    if not candidates_all:
        return []

    candidates: List[Level] = []
    for band in PROXIMITY_BANDS:
        candidates = [lvl for lvl in candidates_all if abs(lvl.price - current_price) / current_price <= band]
        if len(candidates) >= max_levels or band == PROXIMITY_BANDS[-1]:
            break

    candidates.sort(key=lambda lvl: (-lvl.touches, abs(lvl.price - current_price)))
    selected = candidates[:max_levels]
    selected.sort(key=lambda lvl: lvl.price)
    return selected


# --------------------------------------------------------------------------
# Grafik
# --------------------------------------------------------------------------

def plot_chart(df: pd.DataFrame, supports: Sequence[Level], resistances: Sequence[Level],
                title: str, out_path: str) -> None:
    hline_prices = [lvl.price for lvl in supports] + [lvl.price for lvl in resistances]
    hline_colors = ["#2e7d32"] * len(supports) + ["#c62828"] * len(resistances)

    fig, axlist = mpf.plot(
        df,
        type="candle",
        style="yahoo",
        title=title,
        volume=False,
        hlines=dict(hlines=hline_prices, colors=hline_colors, linestyle="--", linewidths=1.0, alpha=0.85)
        if hline_prices
        else None,
        returnfig=True,
        figsize=(14, 8),
        datetime_format="%d-%b %H:%M",
        xrotation=20,
    )

    ax = axlist[0]
    ax.set_ylabel("")  # sag kenardaki varsayilan "Price" etiketi seviye yazilariyla cakisiyor
    x_label_pos = len(df) - 1 + max(2, int(len(df) * 0.01))

    for lvl in supports:
        ax.text(
            x_label_pos, lvl.price, f"D {lvl.price:.3f} ({lvl.touches}x)",
            color="#2e7d32", fontsize=8, va="center", ha="left", clip_on=False,
            fontweight="bold",
        )
    for lvl in resistances:
        ax.text(
            x_label_pos, lvl.price, f"R {lvl.price:.3f} ({lvl.touches}x)",
            color="#c62828", fontsize=8, va="center", ha="left", clip_on=False,
            fontweight="bold",
        )

    fig.subplots_adjust(right=0.82)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Ana akis
# --------------------------------------------------------------------------

def analyze_symbol(tv, display_name: str, symbol: str, exchange: str, n_bars: int, outdir: str) -> None:
    print(f"[{display_name}] veri cekiliyor ({exchange}:{symbol}, 1h, {n_bars} mum)...")
    df = fetch_hourly_data(tv, symbol, exchange, n_bars)
    df = df.tail(n_bars)

    current_price = float(df["close"].iloc[-1])

    swing_highs, swing_lows = find_swing_points(df)
    resistance_levels = cluster_levels(swing_highs)
    support_levels = cluster_levels(swing_lows)

    supports = select_levels(support_levels, current_price, "support", MAX_LEVELS_PER_SIDE)
    resistances = select_levels(resistance_levels, current_price, "resistance", MAX_LEVELS_PER_SIDE)

    print(f"  Guncel fiyat: {current_price:.3f}")
    print(f"  Destek seviyeleri:  {[(round(l.price, 3), l.touches) for l in supports]}")
    print(f"  Direnc seviyeleri:  {[(round(l.price, 3), l.touches) for l in resistances]}")

    if len(supports) < MIN_LEVELS_PER_SIDE:
        print(f"  Uyari: yeterli destek seviyesi bulunamadi ({len(supports)} adet).")
    if len(resistances) < MIN_LEVELS_PER_SIDE:
        print(f"  Uyari: yeterli direnc seviyesi bulunamadi ({len(resistances)} adet).")

    os.makedirs(outdir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = symbol.replace("/", "_")
    out_path = os.path.join(outdir, f"{safe_name}_1h_{timestamp}.png")

    title = f"{display_name} - 1H Destek/Direnc (Guncel: {current_price:.3f})"
    plot_chart(df, supports, resistances, title, out_path)
    print(f"  Kaydedildi: {out_path}")


def build_tv_client(username: str | None, password: str | None):
    from tvDatafeed import TvDatafeed

    if username and password:
        return TvDatafeed(username=username, password=password)
    return TvDatafeed()


def main() -> int:
    parser = argparse.ArgumentParser(description="TradingView metal fiyatlari icin destek/direnc bot.")
    parser.add_argument("--username", default=os.environ.get("TV_USERNAME"), help="TradingView kullanici adi (opsiyonel)")
    parser.add_argument("--password", default=os.environ.get("TV_PASSWORD"), help="TradingView sifresi (opsiyonel)")
    parser.add_argument("--n-bars", type=int, default=DEFAULT_N_BARS, help="Kullanilacak mum sayisi (250-300 onerilir)")
    parser.add_argument("--outdir", default="output", help="PNG dosyalarinin kaydedilecegi klasor")
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Sadece belirtilen gorunen isimlerle calis (orn. 'Gold (XAUUSD)')",
    )
    args = parser.parse_args()

    if not (250 <= args.n_bars <= 320):
        print(f"Uyari: --n-bars {args.n_bars}, onerilen 250-300 araligi disinda.")

    try:
        tv = build_tv_client(args.username, args.password)
    except Exception as exc:  # noqa: BLE001
        print(f"tvDatafeed istemcisi olusturulamadi: {exc}", file=sys.stderr)
        return 1

    symbols_to_run = SYMBOLS
    if args.symbols:
        symbols_to_run = {name: SYMBOLS[name] for name in args.symbols if name in SYMBOLS}
        missing = set(args.symbols) - set(SYMBOLS)
        if missing:
            print(f"Bilinmeyen sembol adlari yok sayildi: {missing}")

    had_error = False
    for display_name, (symbol, exchange) in symbols_to_run.items():
        try:
            analyze_symbol(tv, display_name, symbol, exchange, args.n_bars, args.outdir)
        except Exception as exc:  # noqa: BLE001
            had_error = True
            print(f"[{display_name}] HATA: {exc}", file=sys.stderr)

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
