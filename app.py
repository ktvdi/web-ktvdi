import os
import feedparser
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time

load_dotenv() 
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "rahasia_donk")

# --- HELPER WAKTU ---
def format_pub_date(published_parsed):
    if not published_parsed: return datetime.now().strftime("%H:%M WIB")
    try:
        dt_utc = datetime.fromtimestamp(time.mktime(published_parsed))
        dt_wib = dt_utc + timedelta(hours=7) # Konversi ke WIB
        
        now = datetime.now()
        # Jika hari ini, tampilkan Jam saja biar ringkas
        if dt_wib.date() == now.date():
            return f"HARI INI, {dt_wib.strftime('%H:%M')} WIB"
        else:
            return dt_wib.strftime("%d/%m %H:%M WIB")
    except:
        return "BARU SAJA"

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    seen_titles = set()

    # 1. PESAN NATARU (Prioritas Utama)
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': 'SELAMAT MUDIK NATARU 2025. PATUHI RAMBU LALU LINTAS, GUNAKAN SABUK PENGAMAN, DAN ISTIRAHAT JIKA LELAH.',
        'source': 'KORLANTAS POLRI',
        'date': 'PENTING'
    })

    # 2. SUMBER RSS (Updated)
    sources = [
        {'cat': 'LALU LINTAS', 'url': 'https://news.google.com/rss/search?q=info+tol+jasa+marga+macet+when:1d&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'url': 'https://news.google.com/rss/search?q=humas+polri+terkini+when:1d&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'NASIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        # Ganti feed daerah dengan query nusantara agar lebih banyak isi
        {'cat': 'DAERAH', 'url': 'https://news.google.com/rss/search?q=berita+daerah+indonesia+terkini+when:1d&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'OLAHRAGA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            # Sortir waktu terbaru
            if feed.entries:
                feed.entries.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.localtime(0), reverse=True)

            count = 0
            for entry in feed.entries:
                if count >= 4: break # Ambil 4 berita per kategori
                
                # --- PEMBERSIHAN JUDUL (CRITICAL FIX) ---
                raw_title = entry.title
                # Hapus delimiter umum berita: " - ", " | ", ":"
                clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
                
                # Cek filter kata terlarang (Iklan/Saham)
                if any(x in clean_title.lower() for x in ['saham', 'ihsg', 'rekomendasi', 'prediksi togel']):
                    continue

                if clean_title in seen_titles: continue
                
                # Ambil Nama Sumber
                src_name = entry.source.title.upper() if 'source' in entry else "NEWS"
                
                news_items.append({
                    'category': source['cat'],
                    'headline': clean_title.upper(), # HANYA JUDUL (No Description)
                    'source': src_name,
                    'date': format_pub_date(entry.published_parsed)
                })
                seen_titles.add(clean_title)
                count += 1
        
        # Urutan Tampil
        prio = {'HIMBAUAN':0, 'LALU LINTAS':1, 'KEPOLISIAN':2, 'NASIONAL':3, 'DAERAH':4, 'OLAHRAGA':5, 'TEKNOLOGI':6}
        news_items.sort(key=lambda x: prio.get(x['category'], 99))

    except Exception as e:
        print(f"Error: {e}")
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'MENYINKRONKAN DATA...', 'source': 'SYSTEM', 'date': 'NOW'})
        
    return news_items

@app.route('/api/news-live')
def api_news_live(): return jsonify(get_news_data())

@app.route("/", methods=['GET', 'POST'])
def home(): return render_template('maintenance.html', news_list=get_news_data())

if __name__ == "__main__":
    app.run(debug=True)
