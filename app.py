import os
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import google.generativeai as genai
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'dorian_secret_super_key_shaxniy' # Sessiyalar xavfsizligi uchun

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

API_KEYS = [ ""]

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def ask_gemini_with_history(chat_id, user_message, image_path=None):
    conn = get_db_connection()
    db_messages = conn.execute(
        'SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC',
        (chat_id,)
    ).fetchall()
    conn.close()

    gemini_history = []
    for msg in db_messages:
        gemini_history.append({"role": msg['role'], "parts": [msg['content']]})

    for key in API_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(
                model_name='gemini-2.5-flash',
                system_instruction="Sening isming DORIAN. Sen intellektual yordamchisan. Har doim lo'nda va mukammal javob ber."
            )
            chat = model.start_chat(history=gemini_history)
            
            if image_path:
                img = Image.open(image_path)
                response = chat.send_message([user_message if user_message else "Bu rasmni tahlil qil.", img])
            else:
                response = chat.send_message(user_message)
            return response.text
        except Exception as e:
            print(f"❌ Kalitda xatolik: {e}")
            continue
    return "Kechirasiz jigar, barcha API kalitlar band. 😔"

# --- AUTH ROUTES (KIRISH VA RO'YXATDAN O'TISH) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('index'))
        return "Login yoki parol xato, jigar!"
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        
        try:
            conn = get_db_connection()
            conn.execute('INSERT INTO users (name, username, password) VALUES (?, ?, ?)', (name, username, password))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "Bu login band, boshqasini tanlang!"
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ASOSIY SAHIFALAR ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    # Bloknotlarni alohida, Chatlarni alohida olamiz
    notebooks = conn.execute('SELECT * FROM chats WHERE user_id = ? AND type = "notebook" ORDER BY created_at DESC', (session['user_id'],)).fetchall()
    recents = conn.execute('SELECT * FROM chats WHERE user_id = ? AND type = "chat" ORDER BY created_at DESC', (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('index.html', notebooks=notebooks, recents=recents, user_name=session['user_name'])

@app.route('/chat/new', methods=['POST'])
def create_chat():
    if 'user_id' not in session:
        return jsonify({"error": "Avtorizatsiya yo'q"}), 401
        
    data = request.get_json()
    title = data.get('title', "Yangi ob'ekt")
    chat_type = data.get('type', 'chat') # 'chat' yoki 'notebook'
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chats (user_id, title, type) VALUES (?, ?, ?)', (session['user_id'], title, chat_type))
    chat_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return jsonify({"chat_id": chat_id, "title": title, "type": chat_type})

@app.route('/chat/<int:chat_id>/messages', methods=['GET'])
def get_messages(chat_id):
    conn = get_db_connection()
    messages = conn.execute('SELECT role, content, image_path FROM messages WHERE chat_id = ? ORDER BY timestamp ASC', (chat_id,)).fetchall()
    conn.close()
    return jsonify([dict(msg) for msg in messages])

@app.route('/chat/<int:chat_id>/send', methods=['POST'])
def send_message(chat_id):
    user_text = request.form.get('message', '')
    image_file = request.files.get('image')
    
    image_path = None
    if image_file and image_file.filename != '':
        filename = f"{chat_id}_{image_file.filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)

    conn = get_db_connection()
    conn.execute('INSERT INTO messages (chat_id, role, content, image_path) VALUES (?, ?, ?, ?)', (chat_id, 'user', user_text, image_path))
    conn.commit()

    ai_response = ask_gemini_with_history(chat_id, user_text, image_path)

    conn.execute('INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)', (chat_id, 'model', ai_response))
    conn.commit()
    conn.close()

    return jsonify({"user_message": user_text, "image_path": f"/{image_path}" if image_path else None, "ai_response": ai_response})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

