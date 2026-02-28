import os
import subprocess
import time
import shutil
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# إعدادات البوت
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# إنشاء مجلد مؤقت للعمل بداخله (لحل مشكلة الصلاحيات)
TEMP_DIR = "/tmp/bot_work"
if not os.path.exists(TEMP_DIR):
    try:
        os.makedirs(TEMP_DIR)
    except:
        pass

app = Client("pdf_compressor", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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
        process = subprocess.run(command, check=True, timeout=300)
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        print(f"Compression Error: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client, message: Message):
    doc = message.document
    if not doc.file_name.endswith(".pdf"):
        await message.reply("❌ هذا البوت لضغط ملفات PDF فقط.")
        return

    status_msg = await message.reply("⏳ جاري بدء العملية...")
    
    # تحديد المسارات داخل المجلد المؤقت
    input_pdf = os.path.join(TEMP_DIR, f"in_{message.message_id}.pdf")
    output_pdf = os.path.join(TEMP_DIR, f"out_{message.message_id}.pdf")

    try:
        # 1. تحميل الملف مع حد زمني (Timeout)
        # إذا لم يكتمل التحميل خلال دقيقتين، سيتوقف ويخبرك
        await status_msg.edit("📥 جاري تحميل الملف (قد يستغرق وقتاً حسب سرعتك)...")
        
        # محاولة التحميل
        start_dl = time.time()
        await message.download(file_name=input_pdf)
        dl_time = time.time() - start_dl
        
        if not os.path.exists(input_pdf) or os.path.getsize(input_pdf) == 0:
             await status_msg.edit("❌ فشل تحميل الملف. الملف ربما تم حذفه أو لا يمكن الوصول إليه.")
             return

        # 2. ضغط الملف
        await status_msg.edit(f"⚙️ تم التحميل ({dl_time:.1f} ثانية)\n🗜️ جاري الضغط الآن...")
        
        success = compress_pdf(input_pdf, output_pdf)
        
        if not success:
            await status_msg.edit("❌ فشل الضغط أو استغرق وقتاً طويلاً جداً.")
            return

        # 3. الإرسال
        if os.path.exists(output_pdf):
            old_size = os.path.getsize(input_pdf) / (1024 * 1024)
            new_size = os.path.getsize(output_pdf) / (1024 * 1024)
            reduction = ((old_size - new_size) / old_size) * 100 if old_size > 0 else 0
            
            new_filename = f"Compressed_{doc.file_name}"
            
            caption = (
                f"✅ تم الضغط!\n"
                f"من: {old_size:.2f} MB -> إلى: {new_size:.2f} MB\n"
                f"توفير: {reduction:.1f}%"
            )
            
            await message.reply_document(output_pdf, caption=caption, file_name=new_filename)
            await status_msg.delete()
        else:
            await status_msg.edit("❌ لم يتم إنشاء الملف المضغوط.")

    except FloodWait as e:
        await message.reply(f"يرجى الانتظار {e.x} ثانية ثم المحاولة مرة أخرى.")
    except Exception as e:
        await status_msg.edit(f"خطأ: {str(e)}")
        print(f"Error: {e}")
    finally:
        # تنظيف الملفات
        for f in [input_pdf, output_pdf]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

if __name__ == "__main__":
    print("Bot Running...")
    app.run()