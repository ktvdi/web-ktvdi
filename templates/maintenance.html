<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MAINTENANCE - KTVDI</title>
    <link rel="icon" href="{{ url_for('static', filename='icons/icon-192.png') }}">
    
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Roboto+Mono:wght@500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">

    <style>
        /* --- VARIABLES --- */
        :root {
            --corp-blue: #0056b3;       /* Biru BUMN/Pemerintah */
            --corp-dark: #0f172a;       /* Background Gelap Elegan */
            --corp-card: rgba(30, 41, 59, 0.95);
            --border-light: rgba(255, 255, 255, 0.1);
            --text-white: #ffffff;
            --text-gold: #fbbf24;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--corp-dark);
            background-image: linear-gradient(rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.92)), url('https://iili.io/f1LoZfS.md.png');
            background-size: cover;
            background-position: center;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            color: var(--text-white);
            overflow-x: hidden;
        }

        /* --- TOP BAR 1: MUSLIM (SHOLAT) --- */
        .top-bar-muslim {
            width: 100%;
            background: linear-gradient(90deg, #003366, #0056b3);
            color: white;
            height: 35px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.85rem;
            font-weight: 600;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            z-index: 100;
        }

        /* --- TOP BAR 2: KRISTEN/KATOLIK (MISA) --- */
        .top-bar-christian {
            width: 100%;
            background: #1e293b; /* Abu gelap */
            color: #fbbf24; /* Emas */
            height: 35px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            font-weight: 600;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            z-index: 99;
        }

        .flip-content {
            display: flex; align-items: center; gap: 8px; animation: fadeIn 0.5s ease-in-out; white-space: nowrap;
        }

        /* --- MAIN CONTAINER --- */
        .main-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center; /* Center Vertikal */
            align-items: center;
            width: 100%;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            gap: 20px;
        }

        /* --- CARD STYLE --- */
        .card {
            width: 100%;
            background: var(--corp-card);
            border: 1px solid var(--border-light);
            border-top: 4px solid var(--corp-blue);
            border-radius: 8px;
            padding: 25px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
            text-align: center;
        }

        .logo-img { width: 110px; margin-bottom: 15px; }
        
        h1 {
            font-size: 1.8rem; font-weight: 800; margin-bottom: 5px;
            color: white; text-transform: uppercase; letter-spacing: 0.5px;
        }
        .subtitle { color: var(--corp-blue); font-weight: 700; font-size: 0.9rem; letter-spacing: 2px; margin-bottom: 25px; }

        /* ALERT BOX */
        .alert-box {
            background: rgba(59, 130, 246, 0.1);
            border: 1px solid rgba(59, 130, 246, 0.2);
            border-radius: 6px;
            padding: 15px;
            display: flex; align-items: start; gap: 15px; text-align: left;
        }
        .alert-icon { font-size: 1.4rem; color: #60a5fa; margin-top: 2px; }
        .alert-text h3 { color: #60a5fa; font-size: 0.95rem; margin-bottom: 4px; font-weight: 700; }
        .alert-text p { color: #cbd5e1; font-size: 0.85rem; line-height: 1.5; }

        /* COUNTDOWN */
        .cd-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 20px; }
        .cd-item { background: rgba(255,255,255,0.05); border-radius: 6px; padding: 10px; border: 1px solid var(--border-light); }
        .cd-val { font-family: 'Roboto Mono', monospace; font-size: 1.6rem; font-weight: 700; color: white; display: block; }
        .cd-lbl { font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; margin-top: 2px; }

        /* SYSTEM INFO GRID */
        .info-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; width: 100%; margin-top: 20px; }
        .info-item {
            background: rgba(255,255,255,0.03); border: 1px solid var(--border-light);
            border-radius: 6px; padding: 10px; position: relative; text-align: center;
        }
        .info-lbl { font-size: 0.65rem; color: #94a3b8; text-transform: uppercase; display: block; margin-bottom: 4px; }
        .info-val { font-family: 'Roboto Mono', monospace; font-size: 0.9rem; color: white; font-weight: 600; }
        
        /* BATERAI STRIP */
        .battery-card { grid-column: span 4; overflow: hidden; position: relative; background: rgba(0,0,0,0.3); }
        .battery-bar {
            position: absolute; top:0; left:0; height: 100%; width: 0%; z-index: 0;
            background-image: repeating-linear-gradient(45deg, rgba(255,255,255,0.1) 0px, rgba(255,255,255,0.1) 10px, transparent 10px, transparent 20px);
            background-color: #0056b3; transition: width 1s ease; border-right: 2px solid rgba(255,255,255,0.3);
        }
        .bar-safe { background-color: #10b981; } /* Hijau */
        .bar-warn { background-color: #f59e0b; } /* Kuning */
        .bar-low { background-color: #ef4444; }  /* Merah */
        .battery-content { position: relative; z-index: 1; display: flex; justify-content: space-between; align-items: center; padding: 0 10px; }

        /* --- NEWS TICKER (FLIP BOTTOM) --- */
        .news-container {
            width: 100%; max-width: 900px;
            display: flex; height: 60px; 
            background: #0f172a; border-radius: 6px;
            overflow: hidden; border: 1px solid #334155; 
            margin-top: auto; /* Push to bottom in container */
            margin-bottom: 20px;
        }
        .news-label {
            background: var(--corp-blue); color: white; width: 100px;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            font-size: 0.7rem; font-weight: 800; z-index: 2; text-align: center;
            border-right: 1px solid rgba(255,255,255,0.1); flex-shrink: 0;
        }
        .news-viewport {
            flex: 1; position: relative; overflow: hidden;
        }
        
        .news-slide {
            position: absolute; width: 100%; height: 100%;
            display: flex; align-items: center; padding: 0 20px;
            opacity: 0; transform: translateY(30px); transition: all 0.5s ease;
        }
        .news-slide.active { opacity: 1; transform: translateY(0); }
        .news-slide.exit { opacity: 0; transform: translateY(-30px); }

        .cat-tag {
            font-size: 0.65rem; padding: 3px 8px; border-radius: 4px; color: #fff; font-weight: 700;
            margin-right: 10px; text-transform: uppercase; flex-shrink: 0;
        }
        /* Warna Tag Corporate */
        .bg-NASIONAL { background: #0284c7; }
        .bg-KEPOLISIAN { background: #475569; border: 1px solid #94a3b8; }
        .bg-DAERAH { background: #d97706; }
        .bg-TEKNOLOGI { background: #7c3aed; }
        .bg-INFO { background: #334155; }

        .news-title { 
            font-size: 0.9rem; color: white; font-weight: 600; text-transform: uppercase; 
            line-height: 1.3;
        }
        .news-source { color: #94a3b8; margin-left: 8px; font-size: 0.8rem; font-weight: 400; white-space: nowrap; }

        /* FOOTER */
        .footer { text-align: center; font-size: 0.75rem; color: #64748b; padding-bottom: 20px; }

        @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }

        /* --- RESPONSIVE MEDIA QUERIES --- */
        
        /* TABLET */
        @media (max-width: 768px) {
            .info-grid { grid-template-columns: 1fr 1fr; }
            .battery-card { grid-column: span 2; }
        }

        /* MOBILE (HP) - Critical Fixes */
        @media (max-width: 480px) {
            .main-container { padding: 15px; gap: 15px; }
            
            h1 { font-size: 1.4rem; }
            .cd-val { font-size: 1.4rem; }
            
            /* Ticker HP: Lebih tinggi agar teks bisa wrap */
            .news-container { height: 80px; } 
            .news-label { width: 70px; font-size: 0.65rem; }
            
            .news-slide { 
                flex-direction: column; /* Stack vertikal */
                align-items: flex-start; /* Rata kiri */
                justify-content: center;
                padding: 0 15px;
            }
            
            .cat-tag { margin-bottom: 5px; }
            
            .news-title { 
                font-size: 0.8rem; 
                white-space: normal; /* Izinkan wrap */
                overflow: visible;
                display: -webkit-box;
                -webkit-line-clamp: 2; /* Max 2 baris */
                -webkit-box-orient: vertical;
            }
            
            .news-source { font-size: 0.7rem; margin-left: 0; margin-top: 2px; }
            
            .alert-box { flex-direction: column; gap: 10px; }
        }
    </style>
</head>
<body>

    <div class="top-bar-muslim">
        <div class="flip-content" id="prayer-display">
            <i class="fas fa-mosque prayer-icon"></i> MEMUAT JADWAL SHOLAT...
        </div>
    </div>

    <div class="top-bar-christian">
        <div class="flip-content" id="misa-display">
            <i class="fas fa-church prayer-icon"></i> MEMUAT JADWAL MISA...
        </div>
    </div>

    <div class="main-container">
        
        <div class="card">
            <img src="{{ url_for('static', filename='icons/icon-192.png') }}" alt="Logo" class="logo-img">
            <h1>PEMELIHARAAN SISTEM</h1>
            <div class="subtitle">PEMBARUAN KEAMANAN & INFRASTRUKTUR</div>

            <div class="alert-box">
                <i class="fas fa-info-circle alert-icon"></i>
                <div class="alert-text">
                    <h3>STATUS SERVER: MAINTENANCE</h3>
                    <p>Sistem saat ini sedang menjalani proses pembaruan keamanan dan peningkatan kapasitas server. Langkah ini diambil untuk memastikan layanan KTVDI tetap stabil, aman, dan dapat diandalkan bagi seluruh pengguna di Indonesia.</p>
                </div>
            </div>
        </div>

        <div class="card" style="padding: 15px;">
            <div style="font-size: 0.75rem; color: #94a3b8; letter-spacing: 2px; text-transform: uppercase;">MENUJU TAHUN 2026</div>
            <div class="cd-grid">
                <div class="cd-item"><span class="cd-val" id="d">00</span><span class="cd-lbl">HARI</span></div>
                <div class="cd-item"><span class="cd-val" id="h">00</span><span class="cd-lbl">JAM</span></div>
                <div class="cd-item"><span class="cd-val" id="m">00</span><span class="cd-lbl">MENIT</span></div>
                <div class="cd-item"><span class="cd-val" id="s">00</span><span class="cd-lbl">DETIK</span></div>
            </div>
        </div>

        <div class="info-grid">
            <div class="info-item">
                <span class="info-lbl">WAKTU (WIB)</span>
                <span class="info-val" id="clock">00:00:00</span>
            </div>
            <div class="info-item">
                <span class="info-lbl">LOKASI</span>
                <span class="info-val" id="loc" style="color:#4ade80;">...</span>
            </div>
            <div class="info-item">
                <span class="info-lbl">PROVIDER</span>
                <span class="info-val" id="isp" style="color:#4ade80;">...</span>
            </div>
            <div class="info-item">
                <span class="info-lbl">PERANGKAT</span>
                <span class="info-val" id="dev">...</span>
            </div>
            <div class="info-item battery-card">
                <div class="battery-bar" id="bat-bar"></div>
                <div class="battery-content">
                    <div>
                        <span class="info-lbl">DAYA PERANGKAT</span>
                        <span class="info-val" id="bat-txt">--%</span>
                    </div>
                    <i class="fas fa-bolt" style="color: #ffd700; display:none;" id="bat-icon"></i>
                </div>
            </div>
        </div>

    </div>

    <div style="width: 100%; display: flex; justify-content: center; padding: 0 15px;">
        <div class="news-container">
            <div class="news-label">
                <i class="fas fa-newspaper"></i><br>BERITA
            </div>
            <div class="news-viewport" id="news-viewport">
                <div class="news-slide active">
                    <span class="cat-tag bg-INFO">INFO</span>
                    <span class="news-title">MENGHUBUNGKAN KE SERVER BERITA NASIONAL...</span>
                </div>
            </div>
        </div>
    </div>

    <div class="footer">
        &copy; 2025 Komunitas TV Digital Indonesia. All Rights Reserved.
    </div>

    <script id="news-data" type="application/json">
        {{ news_list | tojson }}
    </script>

    <script>
        // --- 1. JADWAL SHOLAT (API) ---
        const muslimCities = ["JAKARTA", "PEKALONGAN", "PURWODADI", "SEMARANG", "SURABAYA", "BANDUNG", "MEDAN", "MAKASSAR", "JAYAPURA"];
        
        async function runPrayerTicker() {
            const display = document.getElementById('prayer-display');
            const today = new Date();
            const dateStr = `${today.getDate()}-${today.getMonth()+1}-${today.getFullYear()}`;
            
            // Pilih kota acak agar variatif tiap refresh
            let city = muslimCities[Math.floor(Math.random() * muslimCities.length)];
            
            try {
                const res = await fetch(`https://api.aladhan.com/v1/timingsByCity/${dateStr}?city=${city}&country=Indonesia&method=20`);
                const data = await res.json();
                const t = data.data.timings;
                
                // Format Tampilan
                display.innerHTML = `<i class="fas fa-mosque prayer-icon"></i> ${city} : IMSAK ${t.Imsak} | SUBUH ${t.Fajr} | MAGHRIB ${t.Maghrib}`;
                
                // Flip Logic (Ganti Kota Tiap 8 Detik)
                setInterval(async () => {
                    city = muslimCities[Math.floor(Math.random() * muslimCities.length)];
                    try {
                        const r2 = await fetch(`https://api.aladhan.com/v1/timingsByCity/${dateStr}?city=${city}&country=Indonesia&method=20`);
                        const d2 = await r2.json();
                        const t2 = d2.data.timings;
                        
                        display.style.opacity = 0;
                        setTimeout(() => {
                            display.innerHTML = `<i class="fas fa-mosque prayer-icon"></i> ${city} : IMSAK ${t2.Imsak} | SUBUH ${t2.Fajr} | MAGHRIB ${t2.Maghrib}`;
                            display.style.opacity = 1;
                        }, 500);
                    } catch(e){}
                }, 8000);

            } catch(e) { display.innerText = "JADWAL SHOLAT OFFLINE"; }
        }
        runPrayerTicker();

        // --- 2. JADWAL MISA (STATIC DATA) ---
        const misaData = [
            { loc: "KATEDRAL JAKARTA", time: "MINGGU: 06.00, 08.30, 11.00, 16.30 WIB" },
            { loc: "KATEDRAL SEMARANG", time: "MINGGU: 05.30, 07.00, 08.45, 16.30 WIB" },
            { loc: "KATEDRAL SURABAYA", time: "MINGGU: 07.00, 09.00, 16.30, 18.30 WIB" },
            { loc: "KATEDRAL MEDAN", time: "MINGGU: 07.00, 09.00, 17.00 WIB" },
            { loc: "GEREJA BLENDUK (GPIB)", time: "MINGGU: 06.00, 09.00, 17.00 WIB" }
        ];

        function runMisaTicker() {
            const display = document.getElementById('misa-display');
            let idx = 0;
            
            setInterval(() => {
                const item = misaData[idx];
                display.style.opacity = 0;
                setTimeout(() => {
                    display.innerHTML = `<i class="fas fa-church prayer-icon"></i> ${item.loc} | ${item.time}`;
                    display.style.opacity = 1;
                }, 500);
                idx = (idx + 1) % misaData.length;
            }, 8000); // Sinkron dengan sholat
            
            // Init awal
            display.innerHTML = `<i class="fas fa-church prayer-icon"></i> ${misaData[0].loc} | ${misaData[0].time}`;
        }
        runMisaTicker();

        // --- 3. BASIC DASHBOARD FUNCTIONS ---
        setInterval(() => { // Countdown
            const diff = new Date("Jan 1, 2026 00:00:00").getTime() - new Date().getTime();
            if(diff>0){
                document.getElementById("d").innerText=Math.floor(diff/864e5);
                document.getElementById("h").innerText=Math.floor((diff%864e5)/36e5);
                document.getElementById("m").innerText=Math.floor((diff%36e5)/6e4);
                document.getElementById("s").innerText=Math.floor((diff%6e4)/1e3);
            }
        }, 1000);

        setInterval(() => { // Clock
            document.getElementById("clock").innerText = new Date().toLocaleTimeString('id-ID', {hour12:false});
        }, 1000);

        // ISP & Location
        fetch('https://ipapi.co/json/').then(r=>r.json()).then(d=>{
            document.getElementById("loc").innerText = (d.city||"Unknown").toUpperCase();
            document.getElementById("isp").innerText = (d.org||"Unknown").toUpperCase();
        }).catch(()=>{ 
            document.getElementById("loc").innerText="OFFLINE"; 
            document.getElementById("isp").innerText="OFFLINE"; 
        });

        // Device
        const ua = navigator.userAgent;
        let dv = "PC/LAPTOP";
        if(/Android/i.test(ua)) dv="ANDROID";
        else if(/iPhone/i.test(ua)) dv="IPHONE";
        document.getElementById("dev").innerText=dv;

        // Battery
        if(navigator.getBattery){
            navigator.getBattery().then(b=>{
                function up(){
                    const l = Math.round(b.level*100);
                    const t = document.getElementById("bat-txt");
                    const bar = document.getElementById("bat-bar");
                    
                    t.innerText = `${l}% ${b.charging?"(CAS)":""}`;
                    bar.style.width = `${l}%`;
                    
                    bar.className = 'battery-bar';
                    if(l>50) bar.classList.add('bar-safe');
                    else if(l>20) bar.classList.add('bar-warn');
                    else bar.classList.add('bar-low');
                    
                    document.getElementById("bat-icon").style.display = b.charging ? 'block' : 'none';
                }
                up(); b.addEventListener('levelchange',up); b.addEventListener('chargingchange',up);
            });
        } else {
            document.getElementById("bat-txt").innerText = "AC POWER";
            document.getElementById("bat-bar").style.width = "100%";
            document.getElementById("bat-bar").classList.add('bar-safe');
        }

        // --- 4. NEWS FLIP ENGINE ---
        let newsData = [];
        try { newsData = JSON.parse(document.getElementById('news-data').textContent); } catch(e){}

        if(newsData.length > 0) {
            const vp = document.getElementById('news-viewport');
            let cIdx = 0;

            function showSlide(idx) {
                vp.innerHTML = '';
                const item = newsData[idx];
                const div = document.createElement('div');
                div.className = 'news-slide active';
                
                let bg = 'bg-INFO';
                if(item.category=='NASIONAL') bg='bg-NASIONAL';
                if(item.category=='KEPOLISIAN') bg='bg-KEPOLISIAN';
                if(item.category=='DAERAH') bg='bg-DAERAH';
                if(item.category=='TEKNOLOGI') bg='bg-TEKNOLOGI';

                div.innerHTML = `
                    <span class="cat-tag ${bg}">${item.category}</span>
                    <div>
                        <span class="news-title">${item.headline}</span>
                        <span class="news-source">- ${item.source}</span>
                    </div>
                `;
                vp.appendChild(div);
            }
            
            showSlide(0);

            // Ganti Berita tiap 6 Detik
            setInterval(() => {
                const current = vp.querySelector('.news-slide');
                if(current) {
                    current.classList.remove('active');
                    current.classList.add('exit');
                }
                cIdx = (cIdx + 1) % newsData.length;
                setTimeout(() => { showSlide(cIdx); }, 500); 
            }, 6000); 
        }
    </script>
</body>
</html>
