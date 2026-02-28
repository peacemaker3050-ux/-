import os
import subprocess
import time
from pyrogram import Client, filters
from pyrogram.types import Message

# ==========================================
# إعدادات البوت (ستأخذها من Railway تلقائياً)
# ==========================================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app = Client("pdf_compressor", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def compress_pdf(input_path, output_path):
    """
    دالة لضغط ملف PDF باستخدام Ghostscript
    """
    try:
        # أمر الضغط باستخدام إعدادات /ebook لتحقيق التوازن بين الحجم والجودة
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
        
        # تشغيل عملية الضغط
        process = subprocess.run(command, check=True, timeout=300) # حد أقصى 5 دقائق للملف الواحد
        return True
    except subprocess.TimeoutExpired:
        print("Error: Compression timed out")
        return False
    except Exception as e:
        print(f"Compression Error: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client, message: Message):
    # التحقق من أن الملف هو PDF
    doc = message.document
    if not doc.file_name.endswith(".pdf"):
        await message.reply("❌ هذا البوت يقوم بضغط ملفات PDF فقط.\nيرجى إرسال ملف بصيغة .pdf")
        return

    status_msg = await message.reply("⏳ جاري استقبال الملف...")
    
    original_name = doc.file_name
    
    # ==========================================
    # التعديل الهام: استخدام مجلد /tmp للملفات المؤقتة
    # ==========================================
    input_pdf = f"/tmp/original_{message.message_id}.pdf"
    output_pdf = f"/tmp/compressed_{message.message_id}.pdf"

    try:
        # 1. تحميل الملف
        start_time = time.time()
        await message.download(file_name=input_pdf)
        
        # 2. ضغط الملف
        await status_msg.edit("⏳ جاري ضغط الملف وتقليل حجمه...")
        success = compress_pdf(input_pdf, output_pdf)
        
        if not success:
            await status_msg.edit("❌ فشلت عملية الضغط. قد يكون الملف تالفاً أو يستغرق وقتاً طويلاً جداً.")
            return

        # 3. التحقق من وجود الملف المضغوط وحساب الحجم
        if os.path.exists(output_pdf):
            old_size = os.path.getsize(input_pdf) / (1024 * 1024)
            new_size = os.path.getsize(output_pdf) / (1024 * 1024)
            
            # منع القسمة على صفر في حالة الحجم 0
            if old_size > 0:
                reduction = ((old_size - new_size) / old_size) * 100
            else:
                reduction = 0

            new_filename = f"Compressed_{original_name}"
            time_taken = round(time.time() - start_time, 2)
            
            caption = (
                f"✅ تم الضغط بنجاح!\n"
                f"📁 الحجم القديم: {old_size:.2f} MB\n"
                f"📁 الحجم الجديد: {new_size:.2f} MB\n"
                f"📉 نسبة التوفير: {reduction:.1f}%\n"
                f"⏱️ الوقت: {time_taken} ثانية\n\n"
                f"يمكنك الآن تمريره (Forward) للبوت الآخر."
            )
            
            # تحذير إذا كان الحجم لا يزال كبيراً
            if new_size > 20:
                caption += "\n⚠️ تنبيه: الملف لا يزال أكبر من 20 ميجا."

            await message.reply_document(
                output_pdf, 
                caption=caption, 
                file_name=new_filename
            )
            await status_msg.delete()
        else:
            await status_msg.edit("❌ حدث خطأ أثناء إنشاء الملف المضغوط.")

    except Exception as e:
        await status_msg.edit(f"⚠️ حدث خطأ غير متوقع: {e}")
        print(f"General Error: {e}")
    finally:
        # ==========================================
        # تنظيف الملفات المؤقتة لعدم ملء السيرفر
        # ==========================================
        if os.path.exists(input_pdf):
            try:
                os.remove(input_pdf)
            except:
                pass
        if os.path.exists(output_pdf):
            try:
                os.remove(output_pdf)
            except:
                pass

if __name__ == "__main__":
    print("Bot started...")
    app.run()