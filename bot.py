import os
import subprocess
import asyncio
import uuid
import time
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# ==========================================
# إعدادات البوت
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# تعريف مجلد العمل المؤقت
TEMP_DIR = "/tmp/bot_work"
try:
    os.makedirs(TEMP_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creating dir: {e}")

# ==========================================
# تهيئة البوت
# ==========================================
# تمت إزالة in_memory=True لمنع تكرار عمليات تسجيل الدخول التي تسبب الحظر
app = Client(
    "my_pdf_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

def compress_pdf(input_path, output_path):
    """
    دالة لضغط ملف PDF باستخدام Ghostscript
    """
    try:
        command = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            input_path
        ]
        # تشغيل الأمر
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"Ghostscript Error: {result.stderr}")
            return False
            
        return True
    except subprocess.TimeoutExpired:
        print("Error: Compression timed out")
        return False
    except Exception as e:
        print(f"Compression Exception: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client: Client, message: Message):
    # تعريف المتغيرات في البداية لتجنب UnboundLocalError
    input_pdf = None
    output_pdf = None
    
    try:
        doc = message.document
        
        # التحقق من أن الملف PDF
        if not doc.file_name.endswith(".pdf"):
            await message.reply("❌ هذا البوت لضغط ملفات PDF فقط.")
            return

        status_msg = await message.reply("⏳ جاري بدء العملية...")
        
        # إنشاء أسماء فريدة للملفات
        random_id = str(uuid.uuid4())[:8]
        input_pdf = os.path.join(TEMP_DIR, f"in_{random_id}.pdf")
        output_pdf = os.path.join(TEMP_DIR, f"out_{random_id}.pdf")

        # 1. التحميل
        await status_msg.edit("📥 جاري تحميل الملف...")
        try:
            await message.download(file_name=input_pdf)
        except Exception as e:
            await status_msg.edit(f"❌ فشل التحميل: {str(e)}")
            return

        # التحقق من وجود الملف وحجمه
        if not os.path.exists(input_pdf) or os.path.getsize(input_pdf) == 0:
            await status_msg.edit("❌ الملف فارغ أو لم يتم تحميله.")
            return

        # 2. الضغط
        await status_msg.edit("⚙️ جاري ضغط الملف...")
        success = compress_pdf(input_pdf, output_pdf)
        
        if not success:
            await status_msg.edit("❌ فشلت عملية الضغط.")
            return

        # 3. الإرسال
        if os.path.exists(output_pdf):
            old_size = os.path.getsize(input_pdf) / (1024 * 1024)
            new_size = os.path.getsize(output_pdf) / (1024 * 1024)
            
            caption = f"✅ تم الضغط.\nمن: {old_size:.2f} MB\nإلى: {new_size:.2f} MB"
            
            await message.reply_document(output_pdf, caption=caption)
            await status_msg.delete()
        else:
            await status_msg.edit("❌ لم يتم إنشاء الملف المضغوط.")

    except FloodWait as e:
        # التعامل مع الحظر داخل المعالج أيضاً
        await asyncio.sleep(e.x)
    except Exception as e:
        try:
            await message.reply(f"🚨 خطأ: {str(e)}")
        except:
            pass
        print(f"Handler Error: {e}")
    finally:
        # التنظيف الآمن للملفات
        for f in [input_pdf, output_pdf]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

# ==========================================
# نظام التشغيل الذكي (يتعامل مع Flood Wait عند البدء)
# ==========================================
async def start_and_run():
    print("Bot is trying to start...")
    while True:
        try:
            await app.start()
            print("✅ Bot started successfully!")
            # إبقاء البرنامج يعمل إلى الأبد
            await asyncio.Event().wait()
        except FloodWait as e:
            print(f"⚠️ Telegram blocked the bot. Waiting for {e.x} seconds...")
            await asyncio.sleep(e.x)
        except Exception as e:
            print(f"❌ Critical error: {e}")
            print("Retrying in 10 seconds...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    # استخدام run_until_complete لتشغيل دالتنا الخاصة
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_and_run())