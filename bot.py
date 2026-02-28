import os
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# إعدادات البوت من متغيرات البيئة
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app = Client("pdf_compressor", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def compress_pdf(input_path, output_path):
    """
    دالة لضغط ملف PDF باستخدام Ghostscript
    """
    try:
        # المعاملات المستخدمة لضغط PDF:
        # -sDEVICE=pdfwrite: لإنشاء ملف PDF جديد
        # -dPDFSETTINGS=/ebook: إعداد توازن ممتاز بين الجودة والحجم (للقراءة على الشاشة)
        # يمكن تغييرها إلى /screen للحجم الأصغر ولكن جودة أقل، أو /printer لجودة أعلى وحجم أكبر
        # -dNOPAUSE -dQUIET -dBATCH: لجعل العملية سريعة وصامتة
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
        process = subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error compressing PDF: {e}")
        return False

@app.on_message(filters.document & ~filters.forwarded)
async def handle_pdf(client, message: Message):
    # التحقق من أن الملف هو PDF
    if not message.document.file_name.endswith(".pdf"):
        await message.reply("❌ هذا البوت يقوم بضغط ملفات PDF فقط.\nيرجى إرسال ملف بصيغة .pdf")
        return

    # رسالة انتظار
    status_msg = await message.reply("⏳ جاري معالجة الملف وضغطه...")
    
    original_name = message.document.file_name
    input_pdf = f"original_{message.message_id}.pdf"
    output_pdf = f"compressed_{message.message_id}.pdf"

    try:
        # 1. تحميل الملف
        await message.download(file_name=input_pdf)
        
        # 2. ضغط الملف
        await status_msg.edit("⏳ جاري تقليل حجم الملف...")
        success = compress_pdf(input_pdf, output_pdf)
        
        if not success:
            await status_msg.edit("❌ فشلت عملية الضغط، قد يكون الملف تالفاً.")
            return

        # حساب الحجم الجديد
        if os.path.exists(output_pdf):
            old_size = os.path.getsize(input_pdf) / (1024 * 1024)
            new_size = os.path.getsize(output_pdf) / (1024 * 1024)
            reduction = ((old_size - new_size) / old_size) * 100
            
            # تسمية الملف الجديد
            new_filename = f"Compressed_{original_name}"
            
            # 3. إرسال الملف المضغوط
            caption = (
                f"✅ تم ضغط الملف بنجاح!\n"
                f"📁 من: {old_size:.2f} MB\n"
                f"📁 إلى: {new_size:.2f} MB\n"
                f"📉 توفير: {reduction:.1f}%\n\n"
                f"يمكنك الآن تمريره (Forward) للبوت الآخر."
            )
            
            if new_size > 20:
                caption += "\n⚠️ الحجم لا يزال أكبر من 20 ميجا، لقد استخدمت أعلى درجات الضغط المتاحة."

            await message.reply_document(output_pdf, caption=caption, file_name=new_filename)
            await status_msg.delete()
        else:
            await status_msg.edit("❌ لم يتم إنشاء الملف المضغوط.")

    except Exception as e:
        await status_msg.edit(f"حدث خطأ: {e}")
    finally:
        # تنظيف الملفات المؤقتة
        if os.path.exists(input_pdf):
            os.remove(input_pdf)
        if os.path.exists(output_pdf):
            os.remove(output_pdf)

print("Bot is running...")
app.run()