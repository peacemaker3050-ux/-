import os
import asyncio
import uuid
import aiohttp
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from pyrogram.errors import FloodWait
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import firebase_admin
from firebase_admin import credentials, messaging
from aiohttp import web

# ==========================================
# 1. الإعدادات والتهيئة
# ==========================================
API_ID = 33165713
API_HASH = "b6d298b99169563f6bf6c6d5102e8e15"
BOT_TOKEN = "8570132502:AAFTegsgQ9oB3lyWawdLolHtzP0puTEKnO0"

# إعدادات Google Drive
CLIENT_ID = '1006485502608-ok2u5i6nt6js64djqluithivsko4mnom.apps.googleusercontent.com'
CLIENT_SECRET = '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'
REFRESH_TOKEN = '1//03SEUMCBTjt1CCgYIARAAGAMSNwF-L9IrecuL1Xr9zf0RZ1b_mGyIP3_hVeJC-IfIWHrpO_knI6JYsgppYXDPnp2pjniVfbeiP2A'
ROOT_FOLDER_NAME = '2nd MEC 2026'

# إعدادات Firebase Realtime Database
FIREBASE_DB_URL = "https://libirary-b2424-default-rtdb.firebaseio.com"

# المستخدمين المصرح لهم
AUTHORIZED_USERS = [5605597142, 5797320196, 6732616473, 5741332811, 5978595535]

# مجلد العمل المؤقت
TEMP_DIR = os.path.join(os.getcwd(), "temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

# ==========================================
# 2. تهيئة الخدمات
# ==========================================
# Firebase
import json
try:
    sa_json = os.environ.get("SERVICE_ACCOUNT_JSON")
    if sa_json:
        sa_dict = json.loads(sa_json)
        cred = credentials.Certificate(sa_dict)
    else:
        cred = credentials.Certificate("service-account.json")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

# Google Drive Credentials
SCOPES = ['https://www.googleapis.com/auth/drive']
drive_credentials = Credentials(
    token=None,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    scopes=SCOPES
)
drive_service = None

# ==========================================
# 3. المتغيرات العامة
# ==========================================
user_states = {}
db_cache = None
last_cache_time = 0
CACHE_DURATION = 60

app = Client("merged_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==========================================
# 4. دوال مساعدة
# ==========================================

async def get_drive_service():
    global drive_service
    if drive_service is None:
        loop = asyncio.get_running_loop()
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
            http = httplib2.Http()
            authorized_http = AuthorizedHttp(drive_credentials, http=http)
            drive_service = await loop.run_in_executor(None, lambda: build('drive', 'v3', http=authorized_http))
        except ImportError:
            print("Warning: google_auth_httplib2 not found, trying default build.")
            drive_service = await loop.run_in_executor(None, lambda: build('drive', 'v3', credentials=drive_credentials))
    return drive_service

async def get_database(force_refresh=False):
    global db_cache, last_cache_time
    now = datetime.now().timestamp()
    if not force_refresh and db_cache and (now - last_cache_time < CACHE_DURATION):
        return db_cache
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{FIREBASE_DB_URL}/db.json") as resp:
                if resp.status == 200:
                    raw = await resp.json()
                    if raw and isinstance(raw.get('data'), str):
                        db_cache = json.loads(raw['data'])
                    else:
                        db_cache = raw if raw else {"database": {}}
                    last_cache_time = now
                    return db_cache
    except Exception as e:
        print(f"DB Fetch Error: {e}")
    return db_cache if db_cache else {"database": {}}

async def save_database(data):
    global db_cache, last_cache_time
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"{FIREBASE_DB_URL}/db.json",
                json={"data": json.dumps(data, ensure_ascii=False)},
                headers={'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    db_cache = data
                    last_cache_time = datetime.now().timestamp()
                    return True
                else:
                    print(f"DB Save Failed with status: {resp.status}")
                    return False
    except Exception as e:
        print(f"DB Save Error: {e}")
    return False

async def get_root_folder_id():
    service = await get_drive_service()
    loop = asyncio.get_running_loop()
    def _find_root():
        results = service.files().list(
            q=f"mimeType='application/vnd.google-apps.folder' and name='{ROOT_FOLDER_NAME}' and trashed=false",
            fields="files(id, name)", supportsAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        folder_metadata = {'name': ROOT_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=folder_metadata, fields='id', supportsAllDrives=True).execute()
        return folder.get('id')
    return await loop.run_in_executor(None, _find_root)

async def find_or_create_folder(folder_name, parent_id):
    service = await get_drive_service()
    loop = asyncio.get_running_loop()
    def _find_or_create():
        results = service.files().list(
            q=f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false and '{parent_id}' in parents",
            fields="files(id, name)", supportsAllDrives=True
        ).execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return folder.get('id')
    return await loop.run_in_executor(None, _find_or_create)

async def upload_to_drive(file_path, file_name, parent_id):
    service = await get_drive_service()
    loop = asyncio.get_running_loop()
    def _upload():
        file_metadata = {'name': file_name, 'parents': [parent_id]}
        mime_type = 'application/pdf'
        if file_name.endswith('.jpg') or file_name.endswith('.jpeg'): mime_type = 'image/jpeg'
        elif file_name.endswith('.png'): mime_type = 'image/png'
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        file = service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True
        ).execute()
        service.permissions().create(
            fileId=file.get('id'),
            body={'role': 'reader', 'type': 'anyone'},
            supportsAllDrives=True
        ).execute()
        link = file.get('webViewLink')
        if link and 'usp=sharing' not in link: link += '&usp=sharing'
        return {'id': file.get('id'), 'link': link}
    return await loop.run_in_executor(None, _upload)

async def send_push_notification(title, body):
    """
    ✅ إشعارات FCM — تُستدعى فقط من رسائل الأطباء النصية (handle_text → act_send_now)
    وليس من رفع الملفات
    """
    loop = asyncio.get_running_loop()
    def _send():
        try:
            if not db_cache or 'userTokens' not in db_cache: return
            tokens = []
            for t_list in db_cache['userTokens'].values():
                tokens.extend(t_list)
            if not tokens:
                print("FCM: No tokens found, skipping notification.")
                return
            messages = [
                messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    token=token
                ) for token in tokens
            ]
            response = messaging.send_each(messages)
            success = sum(1 for r in response.responses if r.success)
            failure = len(response.responses) - success
            print(f"FCM Sent: {success} success, {failure} failure")
        except Exception as e:
            print(f"FCM Error: {e}")
    await loop.run_in_executor(None, _send)

# ==========================================
# 5. دوال المنطق والواجهة
# ==========================================


async def _send_notification_now(db, subject, doctor, content):
    """دالة مساعدة مشتركة: تحفظ الإشعار في DB وتُحدِّث recentUpdates و latestNotificationUpdate"""
    doc_data = db['database'].setdefault(subject, {}).setdefault(doctor, {}).setdefault('root', [])
    notif_folder = next((f for f in doc_data if f.get('name') == "🔔 Notifications"), None)
    if not notif_folder:
        notif_folder = {
            'id': f"notif_{uuid.uuid4()}",
            'name': "🔔 Notifications",
            'type': 'folder',
            'children': []
        }
        doc_data.append(notif_folder)
    notif_folder['children'].insert(0, {
        'id': str(uuid.uuid4()),
        'name': content,
        'date': str(datetime.now()),
        'type': 'notif'
    })
    if 'recentUpdates' not in db: db['recentUpdates'] = []
    now_ms = int(datetime.now().timestamp() * 1000)  # ميلي ثانية مثل Date.now() في JavaScript
    db['recentUpdates'].insert(0, {
        'id': str(uuid.uuid4()),
        'doctor': doctor,
        'subject': subject,
        'message': content,
        'timestamp': now_ms
    })
    if len(db['recentUpdates']) > 5: db['recentUpdates'].pop()
    db['latestNotificationUpdate'] = now_ms

async def get_current_folder_content(db, subject, doctor, path_ids):
    if not db.get('database'):
        db['database'] = {}
    if not db['database'].get(subject):
        db['database'][subject] = {}
    if not db['database'][subject].get(doctor):
        db['database'][subject][doctor] = {}
    if not db['database'][subject][doctor].get('root'):
        db['database'][subject][doctor]['root'] = []
    current_list = db['database'][subject][doctor]['root']
    for fid in path_ids:
        folder = next((item for item in current_list if item.get('id') == fid and item.get('type') == 'folder'), None)
        if folder and 'children' in folder:
            current_list = folder['children']
        else:
            return []
    return current_list

async def render_folder_contents(client, chat_id, message_id, state):
    db = await get_database()
    current_list = await get_current_folder_content(db, state['subject'], state['doctor'], state['folder_path_ids'])
    keyboard = []
    for item in current_list:
        if item.get('type') == 'folder':
            keyboard.append([InlineKeyboardButton(f"📁 {item['name']}", callback_data=f"folder_{item['id']}")])
    keyboard.append([InlineKeyboardButton("⬆️ Upload Here", callback_data="upload_here")])
    keyboard.append([InlineKeyboardButton("➕ Add New Folder", callback_data="add_new_folder")])
    if state['folder_path_ids']:
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    doctor_name = state['doctor']
    path_text = " / ".join(state['folder_path_names'])
    text = f"👨‍⚕️ Doctor: {doctor_name}\n"
    if path_text: text += f"📂 Path: {path_text}\n"
    text += "\nSelect a folder or action:"
    try:
        if message_id:
            await client.edit_message_text(chat_id, message_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await client.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        print(f"Render Error: {e}")

async def execute_upload(client, chat_id, state):
    """
    ✅ رفع الملف بدون ضغط — لا push notification — لا activeAlerts — لا popup
    ✅ ينتظر اكتمال التنزيل في الخلفية إن لزم
    """
    # ── انتظر اكتمال التنزيل (حتى 10 دقائق) ──
    if not state.get('download_done'):
        wait_msg = await client.send_message(chat_id, "⏳ Waiting for download to complete...")
        for _ in range(600):
            await asyncio.sleep(1)
            st = user_states.get(chat_id)
            if not st: return
            if st.get('download_done'): break
        else:
            await client.edit_message_text(chat_id, wait_msg.id, "❌ Download timed out. Please resend the file.")
            if chat_id in user_states: del user_states[chat_id]
            return
        try: await client.delete_messages(chat_id, wait_msg.id)
        except: pass

    if state.get('download_error'):
        await client.send_message(chat_id, f"❌ Download Failed: {state['download_error']}\nPlease resend the file.")
        if chat_id in user_states: del user_states[chat_id]
        return

    status_msg = await client.send_message(chat_id, "⏳ Starting Upload Process...")
    file_path = state['file_path']
    file_name = state['file_name']
    try:
        db = await get_database()
        root_id = await get_root_folder_id()
        folder_names = [state['subject'], state['doctor']] + state['folder_path_names']
        current_drive_id = root_id
        await client.edit_message_text(chat_id, status_msg.id, "📁 Preparing Drive Folders...")
        for name in folder_names:
            current_drive_id = await find_or_create_folder(name, current_drive_id)
        await client.edit_message_text(chat_id, status_msg.id, f"☁️ Uploading: {file_name}...")
        drive_result = await upload_to_drive(file_path, file_name, current_drive_id)
        current_list = await get_current_folder_content(db, state['subject'], state['doctor'], state['folder_path_ids'])
        new_file_data = {
            'id': str(uuid.uuid4()),
            'name': file_name,
            'type': 'file',
            'link': drive_result['link'],
            'driveId': drive_result['id'],
            'ts': int(datetime.now().timestamp() * 1000)
        }
        current_list.append(new_file_data)

        # ✅ رفع الملف: لا activeAlerts، لا recentUpdates، لا latestNotificationUpdate
        # هذه الحقول مخصصة فقط لرسائل الأطباء النصية والتذكيرات
        # حفظ بيانات الملف فقط في database
        if not await save_database(db):
            await client.edit_message_text(chat_id, status_msg.id, "⚠️ File uploaded to Drive but DB update failed. Please retry.")
            return
        path_str = " / ".join(state['folder_path_names'])
        final_text = f"✅ Upload Completed!\n📚 Subject: {state['subject']} / 👨‍⚕️ {state['doctor']}"
        if path_str: final_text += f" / 📂 {path_str}"
        final_text += f"\n📄 File: {file_name}\n🔗 Link: {drive_result['link']}"
        await client.edit_message_text(chat_id, status_msg.id, final_text, disable_web_page_preview=True)
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass
    except Exception as e:
        await client.edit_message_text(chat_id, status_msg.id, f"❌ Upload Failed: {str(e)}")
    finally:
        if chat_id in user_states:
            del user_states[chat_id]

# ==========================================
# 6. معالجات الرسائل
# ==========================================

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    chat_id = message.chat.id
    if chat_id in user_states:
        del user_states[chat_id]
    await message.reply(
        "🕊️ Peace Maker Welcomes You\n"
        "We're Glad To Have You Here!\n\n"
        "📄 Send a file to upload it to Drive\n"
        "💬 Send a text to notify students\n\n"
        "Commands:\n"
        "/start — Show this message\n"
        "/cancel — Cancel current operation"
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message):
    chat_id = message.chat.id
    if chat_id in user_states:
        state = user_states.pop(chat_id)
        # حذف الملف المؤقت إن وُجد
        file_path = state.get('file_path')
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass
        await message.reply("✅ Operation Cancelled Successfully.")
    else:
        await message.reply("ℹ️ No active operation to cancel.")

@app.on_message(filters.document)
async def handle_file(client, message):
    """
    ✅ يعرض قائمة المواد فوراً — التنزيل في الخلفية بالتوازي
    ✅ لا push notification — لا activeAlerts — لا popup
    """
    chat_id = message.chat.id
    if chat_id not in AUTHORIZED_USERS: return

    if chat_id in user_states:
        old_state = user_states.pop(chat_id)
        old_path = old_state.get('file_path')
        if old_path and os.path.exists(old_path):
            try: os.remove(old_path)
            except: pass

    doc = message.document
    file_name = doc.file_name or f"file_{uuid.uuid4()}"
    file_size_mb = doc.file_size / (1024 * 1024)

    # ── عرض قائمة المواد فوراً بدون انتظار التنزيل ──
    db = await get_database(force_refresh=True)
    subjects = list(db.get('database', {}).keys())
    keyboard = [[InlineKeyboardButton(sub, callback_data=f"sub_{sub}")] for sub in subjects]

    status_msg = await message.reply(
        f"📄 File: {file_name} ({file_size_mb:.1f} MB)\n"
        f"⏳ Downloading in background...\n\n"
        f"Select Subject (you can select now):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # ── تهيئة الحالة فوراً — file_path=None حتى يكتمل التنزيل ──
    temp_file = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_{file_name}")
    user_states[chat_id] = {
        'step': 'select_subject',
        'file_path': None,
        'file_name': file_name,
        'file_size_mb': file_size_mb,
        'download_done': False,
        'download_error': None,
        'status_msg_id': status_msg.id,
        'folder_path_ids': [],
        'folder_path_names': []
    }

    # ── تشغيل التنزيل في الخلفية ──
    async def _download_background():
        try:
            await message.download(file_name=temp_file)
            if chat_id in user_states:
                user_states[chat_id]['file_path'] = temp_file
                user_states[chat_id]['download_done'] = True
            # تحديث الرسالة: إزالة مؤشر التنزيل
            try:
                st = user_states.get(chat_id)
                if st and st.get('step') in ('select_subject', 'select_doctor', 'navigate_folder', 'confirm_name'):
                    current_markup = (await client.get_messages(chat_id, status_msg.id)).reply_markup
                    await client.edit_message_text(
                        chat_id, status_msg.id,
                        f"📄 File: {file_name} ({file_size_mb:.1f} MB)\n"
                        f"✅ Ready to upload\n\nContinue selecting:",
                        reply_markup=current_markup
                    )
            except: pass
        except Exception as e:
            if chat_id in user_states:
                user_states[chat_id]['download_error'] = str(e)
                user_states[chat_id]['download_done'] = True
            try:
                await client.edit_message_text(
                    chat_id, status_msg.id,
                    f"❌ Download Failed: {str(e)}\nPlease resend the file."
                )
            except: pass

    asyncio.create_task(_download_background())

@app.on_message(filters.text & ~filters.command(["start", "cancel"]))
async def handle_text(client, message):
    """
    ✅ الرسائل النصية هي المصدر الوحيد لـ push notification و popup للطلاب
    """
    chat_id = message.chat.id
    text = message.text
    if chat_id not in AUTHORIZED_USERS: return

    state = user_states.get(chat_id)

    if not state:
        # بداية عملية إشعار جديدة
        user_states[chat_id] = {
            'step': 'select_subject_notification',
            'content': text,
            'folder_path_ids': [],
            'folder_path_names': []
        }
        db = await get_database()
        subjects = list(db.get('database', {}).keys())
        keyboard = [[InlineKeyboardButton(sub, callback_data=f"sub_{sub}")] for sub in subjects]
        await message.reply(
            f"📢 New Notification:\n\"{text}\"\n\nSelect Subject:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if state.get('step') == 'waiting_for_folder_name':
        if len(text) > 50:
            await message.reply("❌ Name too long (max 50 characters).")
            return
        try:
            db = await get_database()
            root_id = await get_root_folder_id()
            drive_path = [state['subject'], state['doctor']] + state['folder_path_names']
            curr_id = root_id
            for name in drive_path:
                curr_id = await find_or_create_folder(name, curr_id)
            new_drive_id = await find_or_create_folder(text, curr_id)

            current_list = await get_current_folder_content(db, state['subject'], state['doctor'], state['folder_path_ids'])
            new_folder = {
                'id': f"folder_{uuid.uuid4()}",
                'name': text, 'type': 'folder', 'driveId': new_drive_id, 'children': []
            }
            current_list.append(new_folder)

            if not await save_database(db):
                await message.reply("❌ Failed to save folder to database. Please try again.")
                return

            state['folder_path_ids'].append(new_folder['id'])
            state['folder_path_names'].append(text)
            state['step'] = 'navigate_folder'

            await render_folder_contents(client, chat_id, None, state)
        except Exception as e:
            print(f"Error creating folder: {e}")
            await message.reply(f"❌ Error: {str(e)}")

    elif state.get('step') == 'waiting_for_new_name':
        state['file_name'] = text.strip()
        state['step'] = 'uploading'
        await execute_upload(client, chat_id, state)

# ==========================================
# 7. معالجات الأزرار
# ==========================================

@app.on_callback_query()
async def handle_callback(client, callback_query):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    state = user_states.get(chat_id)
    msg_id = callback_query.message.id

    if not state:
        await callback_query.answer("⚠️ Session expired. Send /start to begin.")
        return

    try:
        if data == 'cancel_op':
            file_path = state.get('file_path')
            if file_path and os.path.exists(file_path):
                try: os.remove(file_path)
                except: pass
            del user_states[chat_id]
            await client.edit_message_text(chat_id, msg_id, "✅ Operation Cancelled.")
            return

        # ── اختيار المادة ──
        if data.startswith('sub_'):
            if state['step'] not in ('select_subject', 'select_subject_notification'):
                await callback_query.answer()
                return
            subject = data.replace('sub_', '', 1)
            state['subject'] = subject
            state['step'] = 'select_doctor'

            db = await get_database()
            doctors = [d for d in db.get('database', {}).get(subject, {}).keys() if d != 'doctors']
            keyboard = [[InlineKeyboardButton(doc, callback_data=f"doc_{doc}")] for doc in doctors]
            await client.edit_message_text(
                chat_id, msg_id,
                f"📚 Subject: {subject}\n\nSelect Doctor:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        # ── اختيار الدكتور ──
        elif data.startswith('doc_'):
            if state['step'] != 'select_doctor':
                await callback_query.answer()
                return
            doctor = data.replace('doc_', '', 1)
            state['doctor'] = doctor

            # إذا كانت العملية إشعار نصي → اذهب لـ choose_action
            # إذا كانت رفع ملف → اذهب لـ navigate_folder
            if 'content' in state:
                state['step'] = 'choose_action'
                keyboard = [
                    [InlineKeyboardButton("📤 Send Now", callback_data='act_send_now')],
                    [InlineKeyboardButton("⏰ Reminder", callback_data='act_reminder')],
                    [InlineKeyboardButton("❌ Cancel", callback_data='cancel_op')]
                ]
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"👨‍⚕️ Doctor: {doctor}\n\n📢 Message:\n\"{state['content']}\"\n\nChoose Action:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                state['step'] = 'navigate_folder'
                await render_folder_contents(client, chat_id, msg_id, state)

        # ── تأكيد إرسال الإشعار النصي ──
        elif state['step'] == 'choose_action':
            if data == 'act_send_now':
                db = await get_database()
                subject = state['subject']
                doctor  = state['doctor']
                content = state['content']
                await _send_notification_now(db, subject, doctor, content)
                await save_database(db)
                await send_push_notification(f"📢 {doctor} ({subject})", content)
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"✅ Notification Sent!\n👨‍⚕️ Doctor: {doctor}\n📚 Subject: {subject}\n\nIt will appear in the App shortly."
                )
                del user_states[chat_id]


            elif data == 'act_reminder':
                # عرض أيام الأسبوع
                state['step'] = 'reminder_select_day'
                days = [
                    ("Sunday",    0), ("Monday",   1), ("Tuesday",  2),
                    ("Wednesday", 3), ("Thursday", 4), ("Friday",   5),
                    ("Saturday",  6), ("Every Day", -1)
                ]
                keyboard = [[InlineKeyboardButton(name, callback_data=f"rday_{val}")] for name, val in days]
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_op')])
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"⏰ Reminder Setup\n📢 Message: \"{state['content']}\"\n\nSelect Day:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif state['step'] == 'reminder_select_day':
            if data.startswith('rday_'):
                day_val = int(data.replace('rday_', '', 1))
                state['reminder_day'] = day_val
                state['step'] = 'reminder_select_hour'
                # عرض ساعات من 0 إلى 23 بصفوف 4
                hours = list(range(0, 24))
                keyboard = []
                row = []
                for h in hours:
                    label = f"{str(h).zfill(2)}:00"
                    row.append(InlineKeyboardButton(label, callback_data=f"rhour_{h}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_op')])
                day_names = {0:"Sunday",1:"Monday",2:"Tuesday",3:"Wednesday",4:"Thursday",5:"Friday",6:"Saturday",-1:"Every Day"}
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"⏰ Reminder Setup\n📅 Day: {day_names.get(day_val,'')}\n\nSelect Hour:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif state['step'] == 'reminder_select_hour':
            if data.startswith('rhour_'):
                hour_val = int(data.replace('rhour_', '', 1))
                state['reminder_hour'] = hour_val
                state['step'] = 'reminder_select_minute'
                # دقائق بفرق 5 دقائق: 0,5,10,...,55
                minutes = list(range(0, 60, 5))
                keyboard = []
                row = []
                for m in minutes:
                    label = f"{str(hour_val).zfill(2)}:{str(m).zfill(2)}"
                    row.append(InlineKeyboardButton(label, callback_data=f"rmin_{m}"))
                    if len(row) == 4:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)
                keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_op')])
                day_names = {0:"Sunday",1:"Monday",2:"Tuesday",3:"Wednesday",4:"Thursday",5:"Friday",6:"Saturday",-1:"Every Day"}
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"⏰ Reminder Setup\n📅 Day: {day_names.get(state['reminder_day'],'')}\nSelect Minute:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif state['step'] == 'reminder_select_minute':
            if data.startswith('rmin_'):
                min_val = int(data.replace('rmin_', '', 1))
                hour_val = state['reminder_hour']
                day_val  = state['reminder_day']
                subject  = state['subject']
                doctor   = state['doctor']
                content  = state['content']
                time_str = f"{str(hour_val).zfill(2)}:{str(min_val).zfill(2)}"
                day_names = {0:"Sunday",1:"Monday",2:"Tuesday",3:"Wednesday",4:"Thursday",5:"Friday",6:"Saturday",-1:"Every Day"}

                db = await get_database()

                # ── أرسل الإشعار الآن أيضاً ──
                await _send_notification_now(db, subject, doctor, content)
                await save_database(db)
                await send_push_notification(f"📢 {doctor} ({subject})", content)

                # ── أضف التذكير التلقائي إلى schedules ──
                db2 = await get_database()
                if 'schedules' not in db2: db2['schedules'] = []
                # احسب تاريخ التنفيذ الفعلي (أول يوم مطابق من الآن)
                from datetime import timedelta
                now_dt = datetime.now()
                if day_val == -1:
                    # كل يوم → غداً في نفس الوقت
                    target_dt = now_dt.replace(hour=hour_val, minute=min_val, second=0, microsecond=0) + timedelta(days=1)
                else:
                    # day_val: 0=Sunday,1=Monday,...,6=Saturday
                    # Python weekday: 0=Monday,...,6=Sunday
                    py_day_map = {0:6,1:0,2:1,3:2,4:3,5:4,6:5}
                    target_py_day = py_day_map[day_val]
                    days_ahead = (target_py_day - now_dt.weekday()) % 7
                    if days_ahead == 0:
                        # نفس اليوم — انتظر الأسبوع القادم إذا فات الوقت
                        check_dt = now_dt.replace(hour=hour_val, minute=min_val, second=0, microsecond=0)
                        days_ahead = 7 if check_dt <= now_dt else 0
                    target_dt = (now_dt + timedelta(days=days_ahead)).replace(
                        hour=hour_val, minute=min_val, second=0, microsecond=0
                    )
                db2['schedules'].append({
                    'id': str(uuid.uuid4()),
                    'subject': subject,
                    'doctor': doctor,
                    'message': content,
                    'day': day_val,
                    'time': time_str,
                    'target_date': target_dt.strftime('%Y-%m-%d'),
                    'active': True,
                    'lastTriggered': 0
                })
                await save_database(db2)

                await client.edit_message_text(
                    chat_id, msg_id,
                    f"✅ Notification Sent Now!\n"
                    f"⏰ Auto-Reminder Set: {day_names.get(day_val,'')} at {time_str}\n"
                    f"👨\u200d⚕️ Doctor: {doctor}\n📚 Subject: {subject}\n\n"
                    f"It will appear in the App at the scheduled time."
                )
                del user_states[chat_id]

        # ── التنقل في المجلدات ──
        elif state['step'] == 'navigate_folder':
            if data == 'back':
                if state['folder_path_ids']:
                    state['folder_path_ids'].pop()
                    state['folder_path_names'].pop()
                    await render_folder_contents(client, chat_id, msg_id, state)
                else:
                    state['step'] = 'select_doctor'
                    db = await get_database()
                    subject = state['subject']
                    doctors = [d for d in db.get('database', {}).get(subject, {}).keys() if d != 'doctors']
                    keyboard = [[InlineKeyboardButton(doc, callback_data=f"doc_{doc}")] for doc in doctors]
                    await client.edit_message_text(
                        chat_id, msg_id,
                        f"📚 Subject: {subject}\n\nSelect Doctor:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )

            elif data == 'add_new_folder':
                state['step'] = 'waiting_for_folder_name'
                await client.edit_message_text(chat_id, msg_id, "📁 Enter the new folder name:")

            elif data.startswith('folder_'):
                if not state.get('subject') or not state.get('doctor'):
                    await callback_query.answer("⚠️ Old session button. Please use current list.")
                    return
                fid = data.replace('folder_', '', 1)
                db = await get_database()
                current_list = await get_current_folder_content(db, state['subject'], state['doctor'], state['folder_path_ids'])
                folder = next((f for f in current_list if f['id'] == fid and f.get('type') == 'folder'), None)
                if folder:
                    state['folder_path_ids'].append(fid)
                    state['folder_path_names'].append(folder['name'])
                    await render_folder_contents(client, chat_id, msg_id, state)
                else:
                    print(f"Critical Error: Folder {fid} not found. Available: {[f.get('id') for f in current_list]}")
                    await callback_query.answer("❌ Folder not found. Try again.")

            elif data == 'upload_here':
                state['step'] = 'confirm_name'
                keyboard = [
                    [InlineKeyboardButton("✅ Same Name", callback_data='act_same')],
                    [InlineKeyboardButton("✏️ Rename", callback_data='act_rename')],
                    [InlineKeyboardButton("❌ Cancel", callback_data='cancel_op')]
                ]
                path = " / ".join(state['folder_path_names'])
                if path: path = " / " + path
                await client.edit_message_text(
                    chat_id, msg_id,
                    f"📍 Location: {state['subject']} / {state['doctor']}{path}\n"
                    f"📄 File: {state['file_name']}\n\n"
                    f"Choose Action:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        # ── تأكيد اسم الملف ──
        elif state['step'] == 'confirm_name':
            if data == 'act_same':
                await execute_upload(client, chat_id, state)
            elif data == 'act_rename':
                state['step'] = 'waiting_for_new_name'
                await client.send_message(chat_id, "✏️ Send the new file name now:")
                try: await client.delete_messages(chat_id, msg_id)
                except: pass

    except Exception as e:
        print(f"Callback Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # تجاهل QUERY_ID_INVALID بهدوء — يحدث عند انتهاء مهلة الـ 30 ثانية
        try:
            await callback_query.answer()
        except Exception:
            pass

# ==========================================
# 8. خادم صغير للحذف
# ==========================================
routes = web.RouteTableDef()

@routes.post('/delete-drive-file')
async def delete_handler(request):
    try:
        data = await request.json()
        file_id = data.get('fileId')
        if file_id:
            service = await get_drive_service()
            loop = asyncio.get_running_loop()
            def _delete():
                try:
                    service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                except Exception as e:
                    print(f"Drive delete error: {e}")
            await loop.run_in_executor(None, _delete)
            return web.json_response({'success': True})
    except Exception as e:
        print(f"API Delete Error: {e}")
    return web.json_response({'success': False})

# ==========================================
# 9. نظام التذكيرات التلقائي (Scheduler)
# ==========================================
async def check_schedules():
    """
    ✅ الـ Scheduler يُرسل push notification فقط لرسائل الجدول الزمني
    وليس للملفات — سلوك متسق مع handle_text
    """
    print("📅 Scheduler Active: Checking for reminders every minute.")
    while True:
        try:
            # day_map: تحويل weekday() (0=Monday) إلى نظام التطبيق (0=Sunday)
            day_map = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}
            now = datetime.now()
            current_day_app = day_map[now.weekday()]
            current_time = f"{str(now.hour).zfill(2)}:{str(now.minute).zfill(2)}"

            # force_refresh=False لأن الـ scheduler يعمل كل دقيقة والكاش كافٍ
            db = await get_database()
            schedules = db.get('schedules', [])

            if not schedules:
                await asyncio.sleep(60)
                continue

            db_updated = False

            for sch in schedules:
                if not sch.get('active', False):
                    continue

                # التحقق من اليوم (-1 يعني كل يوم)
                if sch.get('day', -1) != -1 and sch['day'] != current_day_app:
                    continue

                # التحقق من الوقت
                if sch.get('time') != current_time:
                    continue

                # تحقق من target_date — يُشغَّل فقط في التاريخ المحدد مرة واحدة
                target_date_str = sch.get('target_date')
                if target_date_str:
                    from datetime import date
                    try:
                        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
                    except:
                        target_date = None
                    if target_date and now.date() != target_date:
                        continue  # لم يحن اليوم المحدد بعد
                else:
                    # schedule قديم بدون target_date — استخدم المنطق القديم
                    last_triggered = sch.get('lastTriggered', 0)
                    last_date = datetime.fromtimestamp(last_triggered).date() if last_triggered > 0 else None
                    if last_date == now.date():
                        continue

                print(f"⏰ Triggering schedule: [{sch.get('subject')} / {sch.get('doctor')}] {sch['message']}")

                # ✅ activeAlerts
                if 'activeAlerts' not in db: db['activeAlerts'] = []
                db['activeAlerts'].append({
                    'id': str(uuid.uuid4()),
                    'subject': sch.get('subject', ''),
                    'doctor': sch.get('doctor', ''),
                    'message': sch['message'],
                    'timestamp': now.timestamp()
                })
                if len(db['activeAlerts']) > 20: db['activeAlerts'].pop(0)

                # ✅ recentUpdates — timestamp بالميلي ثانية مثل Date.now() في JavaScript
                now_ms = int(now.timestamp() * 1000)
                if 'recentUpdates' not in db: db['recentUpdates'] = []
                db['recentUpdates'].insert(0, {
                    'id': str(uuid.uuid4()),
                    'doctor': sch.get('doctor', ''),
                    'subject': sch.get('subject', ''),
                    'message': sch['message'],
                    'timestamp': now_ms
                })
                if len(db['recentUpdates']) > 5: db['recentUpdates'].pop()

                # ✅ latestNotificationUpdate → يُشغّل popup في التطبيق
                sch['lastTriggered'] = now.timestamp()
                db['latestNotificationUpdate'] = now_ms
                # ✅ أوقف الـ schedule بعد التشغيل — مرة واحدة فقط
                sch['active'] = False
                db_updated = True

                # ✅ push notification للتذكيرات
                await send_push_notification(
                    f"⏰ Reminder — {sch.get('doctor', '')} ({sch.get('subject', '')})",
                    sch['message']
                )

            if db_updated:
                saved = await save_database(db)
                if saved:
                    print(f"✅ Scheduler: DB saved at {current_time}")
                else:
                    print(f"⚠️ Scheduler: DB save failed at {current_time}")

        except Exception as e:
            print(f"Scheduler Error: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(60)

async def start_web_server():
    app_web = web.Application()
    app_web.add_routes(routes)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 3000)
    print("🌐 Web Server running on port 3000")
    await site.start()

async def set_bot_commands():
    """✅ تسجيل أوامر البوت في BotFather تلقائياً عند التشغيل"""
    try:
        await app.set_bot_commands([
            BotCommand("start", "Welcome message & instructions"),
            BotCommand("cancel", "Cancel current operation"),
        ])
        print("✅ Bot commands registered successfully.")
    except Exception as e:
        print(f"⚠️ Could not set bot commands: {e}")

# ==========================================
# 10. التشغيل الرئيسي
# ==========================================
async def check_new_files():
    """
    ✅ يراقب الملفات الجديدة كل 60 ثانية
    لو لقى ملف ts أحدث من آخر فحص → يبعت FCM لكل المستخدمين
    يغطي حالة Admin Panel upload (اللي مش بيبعت FCM مباشرة)
    """
    print("📂 New Files Watcher Active: Checking every 60 seconds.")
    last_seen_ts = int(datetime.now().timestamp() * 1000)  # ابدأ من دلوقتي

    while True:
        await asyncio.sleep(60)
        try:
            db = await get_database(force_refresh=True)
            database = db.get('database', {})
            newest_ts = 0
            newest_name = ""
            newest_subject = ""

            # اسكن كل الملفات في كل المجلدات
            def scan(items, subject_key):
                nonlocal newest_ts, newest_name, newest_subject
                if not isinstance(items, list):
                    return
                for item in items:
                    if item.get('type') == 'file' and item.get('ts', 0) > newest_ts:
                        newest_ts = item['ts']
                        newest_name = item.get('name', '')
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
                print(f"🆕 New file detected: {newest_name} ({newest_subject}) ts={newest_ts}")
                await send_push_notification(
                    f"New file   — {newest_subject}",
                    newest_name
                )
                last_seen_ts = newest_ts
            else:
                print(f"📂 No new files since last check (last_ts={last_seen_ts})")

        except Exception as e:
            print(f"New Files Watcher Error: {e}")

async def main():
    await start_web_server()
    asyncio.create_task(check_schedules())
    asyncio.create_task(check_new_files())
    print("🤖 Bot is starting...")
    await app.start()
    await set_bot_commands()
    print("✅ Bot started successfully!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())