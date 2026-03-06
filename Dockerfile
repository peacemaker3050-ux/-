# استخدام صورة بايثون خفيفة
FROM python:3.11-slim

# تحديث النظام
RUN apt-get update && apt-get install -y \
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