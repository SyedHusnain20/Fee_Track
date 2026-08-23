FROM python:3.12-slim

WORKDIR /app

# System deps needed for psycopg2 + Pillow (qrcode) builds, plus
# WeasyPrint's rendering stack (Pango/Cairo/GDK-Pixbuf) for real
# server-side PDF invoice generation, and Liberation fonts so the PDF
# renders with consistent glyphs regardless of the host's fonts.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    curl \
    postgresql-client \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
