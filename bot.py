import os
import subprocess
import asyncio
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# ==========================================
# إعدادات البوت
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

TEMP_DIR = "/tmp/bot_work"
try:
    os.makedirs(TEMP_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creating dir: {e}")

app = Client("my_pdf_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def compress_pdf(input_path, output_path, quality_setting="/ebook"):
    """
    دالة الضغط مع تحديد مستوى الجودة
    """
    try:
        command = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={quality_setting}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            input_path
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        print(f"Compression Error: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client: Client, message: Message):
    current_file = None
    output_file = None
    
    try:
        doc = message.document
        if not doc.file_name.endswith(".pdf"):
            await message.reply("❌ هذا البوت لضغط ملفات PDF فقط.")
            return

        status_msg = await message.reply("⏳ جاري بدء العملية...")
        
        # مسار الملف الأصلي
        random_id = str(uuid.uuid4())[:8]
        original_file = os.path.join(TEMP_DIR, f"org_{random_id}.pdf")
        
        # 1. التحميل
        await status_msg.edit("📥 جاري تحميل الملف الأصلي...")
        try:
            await message.download(file_name=original_file)
        except Exception as e:
            await status_msg.edit(f"❌ فشل التحميل: {str(e)}")
            return

        if not os.path.exists(original_file):
            await status_msg.edit("❌ الملف لم يتم تحميله.")
            return

        # ==========================================
        # حلقة التكرار الذكية للضغط المتعدد
        # ==========================================
        current_file = original_file
        attempts = 0
        max_attempts = 3  # سنحاول الضغط 3 مرات كحد أقصى
        target_size_mb = 20
        
        while attempts < max_attempts:
            attempts += 1
            current_size_mb = os.path.getsize(current_file) / (1024 * 1024)
            
            # التحقق: هل وصلنا للحجم المطلوب؟
            if current_size_mb <= target_size_mb:
                break

            # تحديد جودة الضغط (تقليل الجودة في كل مرة)
            if attempts == 1:
                quality = "/ebook"      # محاولة أولى (جودة جيدة)
                msg_text = "⚙️ جاري الضغط (المحاولة 1)..."
            elif attempts == 2:
                quality = "/screen"     # محاولة ثانية (جودة أقل وحجم أصغر)
                msg_text = "⚙️ الحجم لا يزال كبيراً.. جاري الضغط مرة أخرى (المحاولة 2)..."
            else:
                quality = "/screen"     # محاولة ثالثة قصوى
                msg_text = "⚙️ محاولة أخيرة للضغط الشديد (المحاولة 3)..."

            await status_msg.edit(msg_text)
            
            # إنشاء اسم للملف الجديد
            next_file = os.path.join(TEMP_DIR, f"comp_{random_id}_run{attempts}.pdf")
            
            # عملية الضغط
            success = compress_pdf(current_file, next_file, quality_setting=quality)
            
            if success and os.path.exists(next_file):
                # إذا نجح الضغط، نحذف الملف القديم ونستخدم الجديد كمرحلة تالية
                if current_file != original_file:
                    os.remove(current_file)
                current_file = next_file
            else:
                # إذا فشلت محاولة الضغط، نوقف المحاولات ونرسل الملف الحالي
                break

        # ==========================================
        # النتيجة النهائية
        # ==========================================
        final_size_mb = os.path.getsize(current_file) / (1024 * 1024)
        original_size_mb = os.path.getsize(original_file) / (1024 * 1024)

        if final_size_mb <= target_size_mb:
            caption = f"✅ نجح الضغط!\n📉 من {original_size_mb:.1f} MB إلى {final_size_mb:.1f} MB"
        else:
            caption = f"⚠️ تم الضغط قدر الإمكان.\n📉 من {original_size_mb:.1f} MB إلى {final_size_mb:.1f} MB\n(الملف معقد ولا يمكن الوصول لأقل من 20 ميجا)"

        await message.reply_document(current_file, caption=caption)
        await status_msg.delete()

    except FloodWait as e:
        await asyncio.sleep(e.x)
    except Exception as e:
        try:
            await message.reply(f"🚨 خطأ: {str(e)}")
        except:
            pass
        print(f"Error: {e}")
    finally:
        # تنظيف الملفات المؤقتة
        files_to_clean = [original_file, current_file]
        # ملاحظة: المتغير current_file قد يشير لأحد الملفات الوسيطة
        cleaned_paths = set()
        for f in files_to_clean:
            if f and os.path.exists(f):
                cleaned_paths.add(f)
        
        for f in cleaned_paths:
            try:
                os.remove(f)
            except:
                pass

# ==========================================
# نظام التشغيل
# ==========================================
async def start_and_run():
    print("Bot is trying to start...")
    while True:
        try:
            await app.start()
            print("✅ Bot started successfully!")
            await asyncio.Event().wait()
        except FloodWait as e:
            print(f"⚠️ Flood wait: {e.x}s")
            await asyncio.sleep(e.x)
        except Exception as e:
            print(f"❌ Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_and_run())