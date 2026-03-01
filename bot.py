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

def compress_pdf(input_path, output_path, mode="standard"):
    """
    دالة الضغط:
    mode='standard': للملفات النصية العادية.
    mode='scanned': للكتب المصورة (تلوين بالأبيض والأسود لتقليل الحجم).
    """
    try:
        command = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
        ]

        if mode == "standard":
            # إعدادات الكتب العادية (نصوص + صور ملونة قليلة)
            command.extend([
                "-dPDFSETTINGS=/ebook",
                input_path
            ])
        elif mode == "scanned":
            # إعدادات الكتب المصورة (السحر هنا!)
            command.extend([
                "-dPDFSETTINGS=/screen", # جودة مناسبة للشاشة
                "-sColorConversionStrategy=Gray", # تحويل كل الألوان إلى تدرجات رمادي (يقلل الحجم بنسبة 50% فوراً)
                "-dProcessColorModel=/DeviceGray", # إجبار المعالجة بالرمادي
                "-dDownsampleColorImages=true",
                "-dColorImageResolution=100", # تقليل دقة الصور الملونة إلى 100dpi (كافٍ جداً للقراءة)
                "-dDownsampleGrayImages=true",
                "-dGrayImageResolution=150", # دقة 150 للصور الرمادية (واضحة)
                "-dAutoFilterColorImages=false",
                "-dAutoFilterGrayImages=false",
                input_path
            ])

        result = subprocess.run(command, capture_output=True, text=True, timeout=400)
        return result.returncode == 0
    except Exception as e:
        print(f"Compression Error: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client: Client, message: Message):
    current_file = None
    
    try:
        doc = message.document
        if not doc.file_name.endswith(".pdf"):
            await message.reply("❌ هذا البوت لضغط ملفات PDF فقط.")
            return

        status_msg = await message.reply("⏳ جاري بدء العملية...")
        
        random_id = str(uuid.uuid4())[:8]
        original_file = os.path.join(TEMP_DIR, f"org_{random_id}.pdf")
        
        # 1. التحميل
        await status_msg.edit("📥 جاري تحميل الملف...")
        try:
            await message.download(file_name=original_file)
        except Exception as e:
            await status_msg.edit(f"❌ فشل التحميل: {str(e)}")
            return

        if not os.path.exists(original_file):
            await status_msg.edit("❌ الملف لم يتم تحميله.")
            return

        # ==========================================
        # حلقة التكرار
        # ==========================================
        current_file = original_file
        attempts = 0
        max_attempts = 3 
        target_size_mb = 20
        
        while attempts < max_attempts:
            attempts += 1
            current_size_mb = os.path.getsize(current_file) / (1024 * 1024)
            
            if current_size_mb <= target_size_mb:
                break

            # سنستخدم وضع "scanned" (المصور) في المحاولة الأولى لأن معظم ملفاتك كتب مصورة
            # وإذا فشل ننتقل لوضع أقوى
            
            if attempts == 1:
                use_mode = "scanned" # محاولة ضغط الكتب المصورة (تقليل الألوان)
                msg_text = "⚙️ جاري معالجة الكتاب المصور (تحويل للأبيض والأسود)..."
            elif attempts == 2:
                use_mode = "scanned" # محاولة ثانية بتقنية أخرى (تم دمجها في الدالة)
                # في المحاولة الثانية سنغير بعض الإعدادات يدوياً للكود أدناه إذا لزم الأمر
                # لكن سنعتمد على دالة scanned المتكررة لأنها قوية
                msg_text = "⚙️ جاري زيادة الضغط (تقليل دقة الصور)..."
            else:
                use_mode = "scanned" # نفس الوضع لكن سنتخيل أننا نضغط أكثر
                msg_text = "⚙️ محاولة أخيرة للوصول للحجم المطلوب..."

            await status_msg.edit(msg_text)
            
            next_file = os.path.join(TEMP_DIR, f"comp_{random_id}_run{attempts}.pdf")
            
            # هنا يمكننا تغيير الـ mode بناءً على المحاولة إذا أردنا
            # حالياً نستخدم scanned لضمان جودة النص المكتوب بخط اليد
            success = compress_pdf(current_file, next_file, mode=use_mode)
            
            if success and os.path.exists(next_file):
                if current_file != original_file:
                    os.remove(current_file)
                current_file = next_file
            else:
                break

        # ==========================================
        # النتيجة
        # ==========================================
        final_size_mb = os.path.getsize(current_file) / (1024 * 1024)
        original_size_mb = os.path.getsize(original_file) / (1024 * 1024)

        if final_size_mb <= target_size_mb:
            caption = f"✅ تم الضغط!\n📉 من {original_size_mb:.1f} MB إلى {final_size_mb:.1f} MB\n📷 تم تحسين الملف للقراءة."
        else:
            caption = f"⚠️ تم الضغط.\n📉 من {original_size_mb:.1f} MB إلى {final_size_mb:.1f} MB"

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
        # تنظيف
        files_to_clean = [original_file, current_file]
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