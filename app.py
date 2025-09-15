import os
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, jsonify, request, render_template, redirect, url_for, session

# Muat variabel lingkungan dari file .env
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
# Tambahkan secret key untuk sesi, sangat penting untuk keamanan
app.secret_key = os.environ.get('SECRET_KEY')

# Inisialisasi Firebase Admin SDK
try:
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
        "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
        "universe_domain": "googleapis.com"
    })
    
    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })
    
    ref = db.reference('/')

except Exception as e:
    print(f"Error initializing Firebase: {e}")
    ref = None

# Route utama, akan mengalihkan ke halaman login
@app.route("/")
def home():
    return redirect(url_for('login'))

# Route untuk halaman login (GET dan POST)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        users_ref = ref.child('users')
        user_data = users_ref.get()

        if user_data and username in user_data and user_data[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = "Nama pengguna atau kata sandi salah."
            return render_template('index.html', error=error)
            
    return render_template('index.html')

# Route untuk halaman dashboard (hanya bisa diakses setelah login)
@app.route("/dashboard")
def dashboard():
    if 'username' in session:
        return f"Selamat datang, {session['username']}! Ini adalah halaman dashboard Anda."
    return redirect(url_for('login'))

# Route untuk logout
@app.route("/logout")
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)