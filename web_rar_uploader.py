from flask import Flask, request, render_template_string, session, redirect, url_for
from flask_socketio import SocketIO, emit
import os
import subprocess
import threading
import time
import telebot
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a strong secret
socketio = SocketIO(app, async_mode='eventlet')

# ────── CONFIG ──────
BOT_TOKEN = "7300013146:AAFEGyPcmZUinbtbbQc92A_w8_Ljq7R9gRA"
CHANNEL_ID = "-1003284783808"
USERNAME = "your_username"  # ← Change to your username
PASSWORD = "your_password"  # ← Change to your password
BASE_DIR = "/root"  # VPS base directory (change if needed)
PART_SIZE = "1500M"  # 1.5 GB parts
LOG_FILE = "/root/web_rar_log.txt"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')
bot = telebot.TeleBot(BOT_TOKEN)

# Login page HTML
LOGIN_HTML = """
<!doctype html>
<html><head><title>Login</title></head><body>
<h1>Login to VPS RAR Uploader</h1>
<form method="post">
    Username: <input type="text" name="username"><br>
    Password: <input type="password" name="password"><br>
    <input type="submit" value="Login">
</form>
</body></html>
"""

# Main page HTML with file list & RAR form + live progress
MAIN_HTML = """
<!doctype html>
<html><head><title>VPS RAR Uploader</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
<script>
    var socket = io();
    socket.on('progress', function(msg) {
        document.getElementById('progress').innerHTML = msg.log;
    });
</script></head><body>
<h1>VPS Files/Folders</h1>
<ul>{% for item in items %}
    <li>{{ item }}</li>
{% endfor %}</ul>

<h2>Select File/Folder to RAR & Upload</h2>
<form method="post">
    Path: <input type="text" name="path" placeholder="/root/your_folder_or_file"><br>
    <input type="submit" value="Start RAR & Upload">
</form>

<h2>Live Progress</h2>
<pre id="progress">Waiting for task...</pre>

<a href="/logout">Logout</a>
</body></html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'logged_in' not in session:
        if request.method == 'POST':
            if request.form['username'] == USERNAME and request.form['password'] == PASSWORD:
                session['logged_in'] = True
                return redirect(url_for('index'))
            else:
                return "Invalid credentials!"
        return LOGIN_HTML
    
    items = os.listdir(BASE_DIR)  # List files/folders
    if request.method == 'POST':
        path = request.form['path']
        if os.path.exists(path):
            threading.Thread(target=process_task, args=(path,)).start()  # Background task
            return render_template_string(MAIN_HTML, items=items)
        else:
            return "Path not found!"
    
    return render_template_string(MAIN_HTML, items=items)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

def process_task(path):
    """Background RAR + Upload with live progress"""
    base = path + "_part"
    cmd = ["rar", "a", f"-v{PART_SIZE}", "-m5", "-ep", f"{base}.rar", path]
    
    logging.info(f"Starting RAR for {path}")
    emit('progress', {'log': f"Compressing {path}...\n"}, broadcast=True)
    
    # Run RAR with progress simulation (RAR doesn't have native progress, so simulate)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while process.poll() is None:
        time.sleep(5)  # Simulate checking progress
        emit('progress', {'log': "RAR in progress... (check log for details)\n"}, broadcast=True)
    
    logging.info("RAR completed")
    emit('progress', {'log': "RAR completed! Collecting parts...\n"}, broadcast=True)
    
    # Collect parts
    parts = []
    i = 0
    while True:
        part = f"{base}.rar" if i == 0 else f"{base}.r{i:02d}"
        if os.path.exists(part):
            parts.append(part)
            i += 1
        else:
            break
    
    # Upload to TG
    total = len(parts)
    for idx, part in enumerate(parts, 1):
        size_gb = os.path.getsize(part) / (1024**3)
        log_msg = f"Uploading part {idx}/{total} ({size_gb:.2f} GB)\n"
        emit('progress', {'log': log_msg}, broadcast=True)
        logging.info(log_msg)
        
        for attempt in range(3):
            try:
                with open(part, "rb") as f:
                    bot.send_document(CHANNEL_ID, f, caption=f"Part {idx}/{total} | {os.path.basename(path)}", timeout=3600)
                emit('progress', {'log': "Uploaded!\n"}, broadcast=True)
                break
            except Exception as e:
                err = f"Attempt {attempt+1} failed: {e}\n"
                emit('progress', {'log': err}, broadcast=True)
                logging.error(err)
                time.sleep(30)
    
    emit('progress', {'log': "All done! Task completed.\n"}, broadcast=True)
    logging.info("Task completed")

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
