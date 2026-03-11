import os
import json
import uuid
import asyncio
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

import firebase_admin
from firebase_admin import credentials, messaging
import aiohttp

# Google Drive
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# ==========================================
# 1. Config
# ==========================================
FIREBASE_DB_URL = "https://libirary-b2424-default-rtdb.firebaseio.com"
DRIVE_FOLDER_ID = "1T0MwUb-dc3UN3hMjrio1GVT6lm1mQl4Q"

# Google Drive OAuth credentials (from bot.py)
CLIENT_ID     = '1006485502608-ok2u5i6nt6js64djqluithivsko4mnom.apps.googleusercontent.com'
CLIENT_SECRET = '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'
REFRESH_TOKEN = '1//03tt9LkYllqPGCgYIARAAGAMSNwF-L9Ir5WqaeOyHBPBLEHgbih1R8eVcuF5SiIfoZnjQxYSKOFMJjtPbtkHsE1xTXbuYTmX1t5A'

RAILWAY_URL = "https://web-production-b8f1c.up.railway.app"

# ==========================================
# 2. Firebase init
# ==========================================
try:
    sa_json = os.environ.get("SERVICE_ACCOUNT_JSON")
    if sa_json:
        sa_dict = json.loads(sa_json)
        cred = credentials.Certificate(sa_dict)
    else:
        cred = credentials.Certificate("service-account.json")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    print("✅ Firebase initialized")
except Exception as e:
    print(f"❌ Firebase Init Error: {e}")

# ==========================================
# 3. Google Drive init
# ==========================================
SCOPES = ['https://www.googleapis.com/auth/drive']
drive_credentials = Credentials(
    token=None,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    scopes=SCOPES
)

def get_drive_service():
    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        http = httplib2.Http()
        authorized_http = AuthorizedHttp(drive_credentials, http=http)
        return build('drive', 'v3', http=authorized_http)
    except ImportError:
        return build('drive', 'v3', credentials=drive_credentials)

# ==========================================
# 4. Flask App
# ==========================================
app_flask = Flask(__name__)
CORS(app_flask, origins=["https://peacemaker3050-ux.github.io"])

# ==========================================
# 5. Helper: get database
# ==========================================
db_cache = None
last_cache_time = 0
CACHE_DURATION = 60

def get_database_sync(force_refresh=False):
    global db_cache, last_cache_time
    now = time.time()
    if not force_refresh and db_cache and (now - last_cache_time < CACHE_DURATION):
        return db_cache
    try:
        import requests
        resp = requests.get(f"{FIREBASE_DB_URL}/.json", timeout=10)
        if resp.status_code == 200:
            raw = resp.json()
            parsed = raw
            while parsed and isinstance(parsed.get('data'), str):
                try:
                    parsed = json.loads(parsed['data'])
                except:
                    break
            if parsed and isinstance(parsed.get('data'), dict):
                parsed = parsed['data']
            db_cache = parsed if parsed else {"database": {}}
            last_cache_time = now
            return db_cache
    except Exception as e:
        print(f"DB Fetch Error: {e}")
    return db_cache if db_cache else {"database": {}}

# ==========================================
# 6. Helper: send FCM to all tokens
# ==========================================
def clean_invalid_tokens(user_tokens, token_results, all_tokens):
    """Remove invalid/expired tokens from Firebase"""
    try:
        import requests
        invalid_tokens = set()
        for i, result in enumerate(token_results):
            if not result.success:
                err = str(result.exception)
                if 'registration-token-not-registered' in err or 'invalid-registration-token' in err or 'InvalidRegistration' in err:
                    if i < len(all_tokens):
                        invalid_tokens.add(all_tokens[i])

        if not invalid_tokens:
            return

        print(f"🧹 Cleaning {len(invalid_tokens)} invalid tokens...")
        for safe_email, user_data in user_tokens.items():
            if isinstance(user_data, dict):
                old_tokens = user_data.get('tokens', [])
                new_tokens = [t for t in old_tokens if t not in invalid_tokens]
                if len(new_tokens) != len(old_tokens):
                    user_data['tokens'] = new_tokens
                    requests.put(
                        f"{FIREBASE_DB_URL}/userTokens/{safe_email}.json",
                        json=user_data, timeout=10
                    )
                    print(f"🧹 Cleaned tokens for {safe_email}")
    except Exception as e:
        print(f"Clean tokens error: {e}")

def send_fcm_all(title, body):
    try:
        import requests
        resp = requests.get(f"{FIREBASE_DB_URL}/userTokens.json", timeout=10)
        if resp.status_code != 200:
            return 0, 0
        user_tokens = resp.json()
        if not user_tokens:
            return 0, 0
        tokens = []
        for user_data in user_tokens.values():
            if isinstance(user_data, list):
                tokens.extend(user_data)
            elif isinstance(user_data, dict):
                tokens.extend(user_data.get('tokens', []))
        if not tokens:
            return 0, 0
        messages = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                android=messaging.AndroidConfig(priority='high'),
                apns=messaging.APNSConfig(headers={'apns-priority': '10'}),
                token=token
            ) for token in tokens
        ]
        response = messaging.send_each(messages)
        success = sum(1 for r in response.responses if r.success)
        failure = len(response.responses) - success
        print(f"FCM All: {success} success, {failure} failure")
        if failure > 0:
            clean_invalid_tokens(user_tokens, response.responses, tokens)
        return success, failure
    except Exception as e:
        print(f"FCM Error: {e}")
        return 0, 0

# ==========================================
# 7. Helper: send FCM to new-files-enabled tokens only
# ==========================================
def send_fcm_new_files(title, body):
    try:
        import requests
        resp = requests.get(f"{FIREBASE_DB_URL}/userTokens.json", timeout=10)
        if resp.status_code != 200:
            return 0, 0
        user_tokens = resp.json()
        if not user_tokens:
            return 0, 0
        tokens = []
        for user_data in user_tokens.values():
            if isinstance(user_data, dict):
                if user_data.get('newFilesEnabled', False):
                    tokens.extend(user_data.get('tokens', []))
        if not tokens:
            print("FCM New Files: No opted-in tokens")
            return 0, 0
        messages = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                android=messaging.AndroidConfig(priority='high'),
                apns=messaging.APNSConfig(headers={'apns-priority': '10'}),
                token=token
            ) for token in tokens
        ]
        response = messaging.send_each(messages)
        success = sum(1 for r in response.responses if r.success)
        failure = len(response.responses) - success
        print(f"FCM New Files: {success} success, {failure} failure")
        if failure > 0:
            clean_invalid_tokens(user_tokens, response.responses, tokens)
        return success, failure
    except Exception as e:
        print(f"FCM New Files Error: {e}")
        return 0, 0

# ==========================================
# 8. API Routes
# ==========================================

@app_flask.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "UniBot API"})

# --- Send notification to all users ---
@app_flask.route('/send-notification', methods=['POST'])
def send_notification():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    title = data.get('title', '')
    body  = data.get('body', '')
    if not title or not body:
        return jsonify({"error": "title and body required"}), 400
    success, failure = send_fcm_all(title, body)
    return jsonify({"success": success, "failure": failure})

# --- Helper: get or create folder by name inside a parent ---
def get_or_create_folder(service, name, parent_id):
    # Search for existing folder
    query = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files:
        print(f"📁 Found folder: {name} ({files[0]['id']})")
        return files[0]['id']
    # Create folder
    metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=metadata, fields='id').execute()
    print(f"📁 Created folder: {name} ({folder['id']})")
    return folder['id']

# --- Upload file to Google Drive ---
@app_flask.route('/upload-file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    file        = request.files['file']
    subject     = request.form.get('subject', '')
    doctor      = request.form.get('doctor', '')
    folder_path = request.form.get('folder_path', '')  # e.g. "Lectures/Week1"
    notify      = request.form.get('notify', 'true') == 'true'

    try:
        service = get_drive_service()

        # Navigate/create folder structure: Root → Subject → Doctor → [subfolders]
        current_folder_id = DRIVE_FOLDER_ID

        if subject:
            current_folder_id = get_or_create_folder(service, subject, current_folder_id)
        if doctor:
            current_folder_id = get_or_create_folder(service, doctor, current_folder_id)

        # Handle extra subfolders e.g. "Lectures/Week1"
        if folder_path:
            for part in folder_path.split('/'):
                part = part.strip()
                if part:
                    current_folder_id = get_or_create_folder(service, part, current_folder_id)

        # Upload file into the final folder
        file_content = file.read()
        file_stream  = io.BytesIO(file_content)
        media = MediaIoBaseUpload(file_stream, mimetype=file.mimetype, resumable=True)
        file_metadata = {
            'name': file.filename,
            'parents': [current_folder_id]
        }
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()

        # Make file public
        service.permissions().create(
            fileId=uploaded['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        drive_link = uploaded.get('webViewLink', '')
        file_id    = uploaded.get('id', '')

        print(f"✅ Uploaded: {file.filename} → {subject}/{doctor}/{folder_path}")

        # Send FCM if notify enabled
        if notify:
            send_fcm_new_files(
                f"📂 New file — {subject}",
                file.filename
            )

        return jsonify({
            "success": True,
            "fileId": file_id,
            "fileName": file.filename,
            "link": drive_link
        })
    except Exception as e:
        print(f"Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================
# 9. Background Schedulers
# ==========================================

# --- Poll watcher ---
def poll_watcher():
    import requests, time
    print("🗳️ Poll Watcher started")
    last_poll_id = None
    time.sleep(30)
    while True:
        try:
            db = get_database_sync(force_refresh=True)
            poll = db.get('activePoll')
            if poll and not poll.get('ended', False):
                poll_id = str(poll.get('question', '')) + str(poll.get('endsAt', 0))
                ends_at_ms  = poll.get('endsAt', 0)
                remaining_s = max(0, int((ends_at_ms - time.time() * 1000) / 1000))
                if poll_id != last_poll_id and remaining_s > 0:
                    print(f"🗳️ New poll: {poll.get('question','')}")
                    send_fcm_all(
                        "🗳️ New Poll — Vote Now!",
                        poll.get('question', 'A new poll is waiting for your vote')
                    )
                    last_poll_id = poll_id
        except Exception as e:
            print(f"Poll Watcher Error: {e}")
        time.sleep(30)

# --- Quick Links watcher ---
def quicklinks_watcher():
    import requests, time
    print("🔗 Quick Links Watcher started")
    last_count = -1
    time.sleep(30)
    while True:
        try:
            db = get_database_sync(force_refresh=True)
            links = db.get('quickLinks', [])
            if not isinstance(links, list):
                links = []
            count = len(links)
            if last_count == -1:
                last_count = count
            elif count > last_count:
                new_link = links[-1]
                print(f"🔗 New link: {new_link.get('title','')}")
                send_fcm_all(
                    "🔗 New Link Added",
                    new_link.get('title', 'A new link is now available')
                )
            last_count = count
        except Exception as e:
            print(f"Quick Links Watcher Error: {e}")
        time.sleep(30)

# --- New Files watcher ---
def new_files_watcher():
    import time
    print("📂 New Files Watcher started")
    last_seen_ts = int(time.time() * 1000)
    time.sleep(60)
    while True:
        try:
            db = get_database_sync(force_refresh=True)
            database = db.get('database', {})
            newest_ts      = 0
            newest_name    = ""
            newest_subject = ""

            def scan(items, subject_key):
                nonlocal newest_ts, newest_name, newest_subject
                if not isinstance(items, list):
                    return
                for item in items:
                    if item.get('type') == 'file' and item.get('ts', 0) > newest_ts:
                        newest_ts      = item['ts']
                        newest_name    = item.get('name', '')
                        newest_subject = subject_key
                    if item.get('type') == 'folder':
                        scan(item.get('children', []), subject_key)

            for subject_key, subject_val in database.items():
                if not isinstance(subject_val, dict):
                    continue
                for key, val in subject_val.items():
                    if key == 'doctors':
                        continue
                    if isinstance(val, dict) and 'root' in val:
                        scan(val['root'], subject_key)

            if newest_ts > last_seen_ts:
                print(f"🆕 New file: {newest_name} ({newest_subject})")
                send_fcm_new_files(
                    f"📂 New file — {newest_subject}",
                    newest_name
                )
                last_seen_ts = newest_ts
            else:
                print(f"📂 No new files (last_ts={last_seen_ts})")
        except Exception as e:
            print(f"New Files Watcher Error: {e}")
        time.sleep(60)

# --- Schedules watcher ---
def schedules_watcher():
    import requests as req
    print("⏰ Schedules Watcher started")
    time.sleep(30)
    while True:
        try:
            db = get_database_sync(force_refresh=True)
            schedules = db.get('schedules', [])
            if not isinstance(schedules, list):
                schedules = []

            now = datetime.now()
            current_day  = now.weekday()  # 0=Monday ... 6=Sunday
            current_time = now.strftime('%H:%M')
            changed = False

            for sched in schedules:
                if not sched.get('active', False):
                    continue
                sched_day  = sched.get('day', -1)
                sched_time = sched.get('time', '')
                last_triggered = sched.get('lastTriggered', 0)

                # Check day and time match
                if sched_day != current_day:
                    continue
                if sched_time != current_time:
                    continue

                # Avoid sending twice in same minute
                last_dt = datetime.fromtimestamp(last_triggered / 1000) if last_triggered else None
                if last_dt and last_dt.date() == now.date() and last_dt.strftime('%H:%M') == current_time:
                    continue

                subject = sched.get('subject', '')
                doctor  = sched.get('doctor', '')
                message = sched.get('message', '')

                print(f"⏰ Firing schedule: {subject} - {doctor}: {message}")
                send_fcm_all(
                    f"🔔 Reminder — {doctor} ({subject})",
                    message
                )

                # Update lastTriggered
                sched['lastTriggered'] = int(now.timestamp() * 1000)
                changed = True

            if changed:
                # Save updated schedules back to Firebase
                try:
                    full_db = get_database_sync(force_refresh=True)
                    full_db['schedules'] = schedules
                    import json as _json
                    req.put(
                        f"{FIREBASE_DB_URL}/.json",
                        json={'data': _json.dumps(full_db)},
                        timeout=10
                    )
                    print("⏰ Schedules updated in Firebase")
                except Exception as e:
                    print(f"⏰ Schedule save error: {e}")

        except Exception as e:
            print(f"Schedules Watcher Error: {e}")
        time.sleep(60)  # Check every minute

# ==========================================
# 10. Start
# ==========================================
def start_watchers():
    threading.Thread(target=poll_watcher,        daemon=True).start()
    threading.Thread(target=quicklinks_watcher,  daemon=True).start()
    threading.Thread(target=new_files_watcher,   daemon=True).start()
    threading.Thread(target=schedules_watcher,   daemon=True).start()

# Auto-start watchers when gunicorn loads the module
start_watchers()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 UniBot API running on port {port}")
    app_flask.run(host='0.0.0.0', port=port)