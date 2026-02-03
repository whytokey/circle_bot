# Используем легкий образ Python
FROM python:3.10-slim

# Устанавливаем ffmpeg и системные зависимости
RUN apt-get update && apt-get install -y ffmpeg libsm6 libxext6 && apt-get clean

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY . .

# Команда для запуска
CMD ["python", "main.py"]