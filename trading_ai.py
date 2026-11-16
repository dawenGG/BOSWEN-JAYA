import json, os, re, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
METAAPI_TOKEN = os.environ.get("METAAPI_TOKEN", "").strip()
METAAPI_ACCOUNT_ID = os.environ.get("METAAPI_ACCOUNT_ID", "").strip()

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY masih kosong! Cek lagi di Settings -> Secrets -> Actions.")

client = genai.Client(api_key=API_KEY)
STATE_FILE = "porto_cent.json"

if os.path.exists(STATE_FILE):
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        porto = json.load(f)
else:
    porto = {
        "saldo_usc": 300.0,
        "update_terakhir": "-",
        "analisa_terakhir": "Belum ada",
        "posisi": None,
        "riwayat": [],
    }

def waktu_wib():
    return datetime.now(timezone(timedelta(hours=7))).strftime("%d %b %H:%M WIB")

def simpan_porto():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(porto, f, indent=2, ensure_ascii=False)

def ambil_harga_h1():
    try:
        url_k = "https://api.kraken.com/0/public/OHLC?pair=EURUSD&interval=60"
        req_k = urllib.request.Request(url_k, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_k, timeout=20) as res:
            kdata = json.loads(res.read().decode())
        pair_key = [k for k in kdata["result"].keys() if k != "last"][0]
        hasil = [float(c[4]) for c in kdata["result"][pair_key][-70:]]
        if len(hasil) >= 55:
            return hasil
    except Exception as e:
        print("Info Kraken:", e)

    url_y = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1h&range=10d"
    req_y = urllib.request.Request(url_y, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req_y, timeout=20) as res:
        data = json.loads(res.read().decode())
    closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return [float(c) for c in closes if c is not None]

def hitung_ema(data, periode):
    k = 2 / (periode + 1)
    ema = sum(data[:periode]) / periode
    for harga in data[periode:]:
        ema = harga * k + ema * (1 - k)
    return round(ema, 5)

def hitung_rsi(data, periode=14):
    untung, rugi = [], []
    for i in range(1, len(data)):
        selisih = data[i] - data[i - 1]
        untung.append(max(selisih, 0))
        rugi.append(max(-selisih, 0))
    avg_gain = sum(untung[-periode:]) / periode
    avg_loss = sum(rugi[-periode:]) / periode
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def kirim_order_fbs(aksi, sl, tp):
    if not METAAPI_TOKEN or not METAAPI_ACCOUNT_ID:
        return "Mode Simulasi"
    url = f"https://mt-client-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts/{METAAPI_ACCOUNT_ID}/trade"
    payload = json.dumps({
        "actionType": "ORDER_TYPE_BUY" if aksi == "BUY" else "ORDER_TYPE_SELL",
        "symbol": "EURUSD",
        "volume": 0.01,
        "stopLoss": sl,
        "takeProfit": tp,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "auth-token": METAAPI_TOKEN,
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return f"Terkirim ke FBS MT5 ({res.status})"
    except urllib.error.HTTPError as e:
        return f"Gagal order MT5: {e.code}"
    except Exception as e:
        return f"Error koneksi MT5: {e}"

def main():
    jam = waktu_wib()
    closes = ambil_harga_h1()
    harga_skrg = round(closes[-1], 5)
    ema20 = hitung_ema(closes, 20)
    ema50 = hitung_ema(closes, 50)
    rsi14 = hitung_rsi(closes, 14)

    porto["update_terakhir"] = jam

    pos = porto.get("posisi")
    if pos:
        kena_tp = (pos["tipe"] == "BUY" and harga_skrg >= pos["tp"]) or (pos["tipe"] == "SELL" and harga_skrg <= pos["tp"])
        kena_sl = (pos["tipe"] == "BUY" and harga_skrg <= pos["sl"]) or (pos["tipe"] == "SELL" and harga_skrg >= pos["sl"])
        if kena_tp or kena_sl:
            hasil_usc = 4.0 if kena_tp else -2.0
            porto["saldo_usc"] = round(porto["saldo_usc"] + hasil_usc, 2)
            status = "PROFIT +4.0 USC" if kena_tp else "STOP LOSS -2.0 USC"
            porto["riwayat"].insert(0, {"waktu": jam, "status": status, "saldo": porto["saldo_usc"]})
            porto["analisa_terakhir"] = f"Posisi {pos['tipe']} ditutup: {status}"
            porto["posisi"] = None
            simpan_porto()
        else:
            porto["analisa_terakhir"] = f"Tahan posisi {pos['tipe']} (Harga skrg: {harga_skrg} | SL: {pos['sl']} | TP: {pos['tp']})"
            simpan_porto()
            return

    if porto["saldo_usc"] <= 240.0:
        porto["analisa_terakhir"] = "Trading dihentikan otomatis oleh Risk Manager karena batas rugi tercapai."
        simpan_porto()
        return

    prompt = f"""
    Kamu adalah Senior Forex Trader konservatif untuk pair EURUSD timeframe H1.
    Data saat ini: Harga={harga_skrg}, EMA20={ema20}, EMA50={ema50}, RSI14={rsi14}.
    Aturan: BUY jika EMA20 > EMA50 dan RSI antara 45-68. SELL jika EMA20 < EMA50 dan RSI antara 32-55. Selain itu HOLD.
    Balas HANYA JSON valid:
    {{"keputusan": "BUY atau SELL atau HOLD", "alasan": "1 kalimat singkat bahasa Indonesia"}}
    """
    res = client.models.generate_content(
        model="gemini-3.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
    )
    m = re.search(r"\{.*\}", res.text, re.S)
    analisa = json.loads(m.group(0) if m else res.text)

    keputusan = analisa.get("keputusan", "HOLD").upper()
    alasan = analisa.get("alasan", "")
    status_order = ""

    if keputusan in ("BUY", "SELL"):
        jarak_sl = 0.0020
        jarak_tp = 0.0040
        sl = round(harga_skrg - jarak_sl if keputusan == "BUY" else harga_skrg + jarak_sl, 5)
        tp = round(harga_skrg + jarak_tp if keputusan == "BUY" else harga_skrg - jarak_tp, 5)
        porto["posisi"] = {"tipe": keputusan, "entry": harga_skrg, "sl": sl, "tp": tp}
        info_mt5 = kirim_order_fbs(keputusan, sl, tp)
        status_order = f" [{info_mt5}]"

    porto["analisa_terakhir"] = f"{keputusan} (Harga {harga_skrg}){status_order} — {alasan}"
    simpan_porto()

if __name__ == "__main__":
    main()
