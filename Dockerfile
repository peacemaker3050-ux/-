# استخدام صورة بايثون خفيفة
FROM python:3.9-slim

# تحديث النظام وتثبيت Ghostscript والملفات الأساسية
RUN apt-get update && apt-get install -y \
    ghostscript \
    curl \
    && rm -rf /var/lib/apt/lists/*

# تعيين مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات الكود
COPY . .

# أمر تشغيل البوت
CMD ["python", "bot.py"]
