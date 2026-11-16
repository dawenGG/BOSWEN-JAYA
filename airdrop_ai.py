import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY masih kosong!")

client = genai.Client(api_key=API_KEY)
OUT_FILE = "airdrop_list.json"

def waktu_wib():
    return datetime.now(timezone(timedelta(hours=7)))

# Biar hemat kuota API, update daftar airdrop cukup tiap 3 jam sekali
if os.path.exists(OUT_FILE):
    try:
        lama = json.load(open(OUT_FILE, "r", encoding="utf-8"))
        last_ts = lama.get("timestamp", 0)
        if waktu_wib().timestamp() - last_ts < 10500 and lama.get("items"):
            print("Daftar airdrop masih segar, skip update jam ini.")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass

def ambil_info_kripto():
    kandidat_info = []

    # Sumber 1: Proyek baru yang baru dapet pendanaan VC (DeFiLlama)
    try:
        req = urllib.request.Request("https://api.llama.fi/raises", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.loads(res.read().decode())
        raises = data.get("raises", [])[-15:]
        for r in reversed(raises):
            nama = r.get("name", "")
            dana = r.get("amount", 0)
            kat = r.get("category", "")
            chain = ", ".join(r.get("chains", [])[:2])
            if nama:
                kandidat_info.append(f"[Pendanaan Baru] {nama} dapet ${dana}M | Kategori: {kat} | Chain: {chain}")
    except Exception as e:
        print("Info DeFiLlama:", e)

    # Sumber 2: Berita airdrop & testnet terbaru
    try:
        req2 = urllib.request.Request("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=20) as res:
            ndata = json.loads(res.read().decode())
        kata_kunci = ("airdrop", "testnet", "points", "incentivized", "claim", "mainnet", "quest")
        for item in ndata.get("Data", [])[:35]:
            judul = item.get("title", "")
            if any(k in judul.lower() for k in kata_kunci):
                kandidat_info.append(f"[News] {judul} ({item.get('source', '')})")
    except Exception as e:
        print("Info News:", e)

    if not kandidat_info:
        kandidat_info = [
            "[Pendanaan Baru] Proyek Layer-2 & DeFi Testnet fase awal tanpa token",
            "[News] Program poin ekosistem Solana, Base, dan Monad Testnet"
        ]
    return "\n".join(kandidat_info[:22])

def tanya_gemini(prompt):
    kandidat = [
        "gemini-3.0-flash",
        "gemini-3-flash-preview",
        "gemini-flash-latest",
        "gemini-2.5-flash",
    ]
    try:
        for m in client.models.list():
            nama = m.name.replace("models/", "")
            if "gemini" in nama and "flash" in nama and not any(x in nama for x in ["image", "audio", "tts", "thinking"]):
                if nama not in kandidat:
                    kandidat.append(nama)
    except Exception:
        pass

    for model_name in kandidat:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.35),
            )
            if res and res.text:
                return res.text
        except Exception:
            continue
    raise RuntimeError("Gagal panggil Gemini untuk analisa airdrop.")

def main():
    now = waktu_wib()
    raw_data = ambil_info_kripto()

    prompt = f"""
    Kamu adalah tim Pemburu Airdrop Kripto (Alpha Hunter & Anti-Scam Analyst).
    Dari data pendanaan proyek baru dan berita kripto hari ini:
    {raw_data}

    Pilih 4 peluang airdrop atau testnet paling potensial (utamakan yang gratis / modal kecil dan belum rilis token).
    Balas HANYA JSON valid tanpa markdown:
    {{
      "ringkasan": "1 kalimat singkat kondisi perburuan airdrop hari ini",
      "items": [
        {{
          "nama": "Nama Proyek",
          "tipe": "Testnet Gratis / Retroactive / Poin",
          "potensi": "Tinggi / Sedang",
          "modal": "Gratis ($0) atau Gas Fee Kecil",
          "langkah": "2 kalimat singkat cara mulai garap dan tips aman anti-scam"
        }}
      ]
    }}
    """
    teks = tanya_gemini(prompt)
    m = re.search(r"\{.*\}", teks, re.S)
    hasil = json.loads(m.group(0) if m else teks)

    output = {
        "timestamp": now.timestamp(),
        "update_terakhir": now.strftime("%d %b %H:%M WIB"),
        "ringkasan": hasil.get("ringkasan", "Pantauan proyek potensial terbaru."),
        "items": hasil.get("items", [])[:5],
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("Berhasil simpan daftar airdrop:", len(output["items"]))

if __name__ == "__main__":
    main()
