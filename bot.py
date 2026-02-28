import os
import subprocess
import time
import asyncio
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
# التأكد من وجود المجلد
try:
    os.makedirs(TEMP_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creating dir: {e}")

# ==========================================
# تهيئة البوت
# ==========================================
# نستخدم in_memory=True لمنع إنشاء ملفات الجلسة التي قد تسبب مشاكل صلاحيات
app = Client(
    "pdf_compressor_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    in_memory=True 
)

def compress_pdf(input_path, output_path):
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
        # تشغيل وطباعة الأخطاء إن وجدت
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
        return True
    except subprocess.TimeoutExpired:
        print("Error: Compression timed out")
        return False
    except subprocess.CalledProcessError as e:
        print(f"GS Error: {e.stderr}")
        return False
    except Exception as e:
        print(f"General Compression Error: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client: Client, message: Message):
    try:
        doc = message.document
        if not doc.file_name.endswith(".pdf"):
            await message.reply("❌ هذا البوت لضغط ملفات PDF فقط.")
            return

        # محاولة إرسال رسالة البدء
        status_msg = await message.reply("⏳ جاري بدء العملية...")
        
        input_pdf = os.path.join(TEMP_DIR, f"in_{message.message_id}.pdf")
        output_pdf = os.path.join(TEMP_DIR, f"out_{message.message_id}.pdf")

        # 1. التحميل
        await status_msg.edit("📥 جاري التحميل...")
        
        # تحميل مع تجاوز الأخطاء البسيطة
        try:
            await message.download(file_name=input_pdf)
        except Exception as e:
            await status_msg.edit(f"❌ فشل التحميل: {str(e)}")
            return

        if not os.path.exists(input_pdf):
            await status_msg.edit("❌ لم يتم العثور على الملف بعد التحميل.")
            return

        # 2. الضغط
        await status_msg.edit("⚙️ جاري الضغط...")
        success = compress_pdf(input_pdf, output_pdf)
        
        if not success:
            await status_msg.edit("❌ فشلت عملية الضغط (قد يكون الملف تالفاً).")
            return

        # 3. الإرسال
        if os.path.exists(output_pdf):
            old_size = os.path.getsize(input_pdf) / (1024 * 1024)
            new_size = os.path.getsize(output_pdf) / (1024 * 1024)
            
            caption = f"✅ تم الضغط.\nالحجم القديم: {old_size:.2f} MB\nالحجم الجديد: {new_size:.2f} MB"
            
            await message.reply_document(output_pdf, caption=caption)
            await status_msg.delete()
        else:
            await status_msg.edit("❌ فشل إنشاء الملف المضغوط.")

    except FloodWait as e:
        await asyncio.sleep(e.x)
    except Exception as e:
        # هذا الجزء مهم جداً: سيخبرك بالخطأ الحقيقي في التليجرام
        try:
            await message.reply(f"🚨 حدث خطأ في البوت: {str(e)}")
        except:
            pass
        print(f"Critical Error: {e}")
    finally:
        # تنظيف
        for f in [input_pdf, output_pdf]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

# ==========================================
# تشغيل البوت مع طباعة الأخطاء
# ==========================================
if __name__ == "__main__":
    print("Bot is starting...")
    try:
        app.run()
    except Exception as e:
        print(f"Failed to start: {e}")