FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV STEREODESK_DATA_DIR=/data STEREODESK_HOST=0.0.0.0 PORT=18938 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
HEALTHCHECK --interval=8s --timeout=3s --start-period=3s --retries=3 CMD python3 -B -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18938/stereo/health')"
EXPOSE 18938
CMD ["python3", "-B", "app.py"]
