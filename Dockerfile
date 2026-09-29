FROM python:3.11-slim

WORKDIR /app

# Logs reach `docker compose logs` without -u; pip does not leave a layer behind.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencies first, so editing the application does not reinstall them.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5555

# /health needs no auth. Uses the stdlib, so no curl has to be installed.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://127.0.0.1:5555/health',timeout=2).status==200 else 1)"

# main.py starts uvicorn on 0.0.0.0:5555 itself. Do not add --reload here:
# it is for development and would only watch files inside the image.
CMD ["python", "main.py"]
