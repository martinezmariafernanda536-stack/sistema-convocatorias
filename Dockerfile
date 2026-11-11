# Sistema de convocatorias · DGDCI · APC-Colombia — imagen para Hugging Face Spaces (sdk: docker)
FROM python:3.12-slim

# LibreOffice (solo Writer, sin interfaz) para convertir el informe a PDF, y fuentes compatibles con Arial y Calibri
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui fonts-liberation fonts-crosextra-carlito fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face ejecuta el contenedor con el usuario 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
