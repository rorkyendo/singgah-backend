FROM python:3.10-slim

# Install Chromium, ChromeDriver, and runtime libraries needed by Selenium.
# Notes for Debian 12 (Bookworm):
# - libgconf-2-4 and libindicator7 are removed from recent Debian.
# - libgbm1 is required for headless Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    libxss1 \
    libappindicator3-1 \
    libgtk-3-0 \
    libasound2 \
    libgbm1 \
    libxslt1.1 \
    libxml2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Make Chromium discoverable by Selenium with the standard names.
# Also ensure the chromedriver binary is on the PATH as `chromedriver`.
RUN ln -s /usr/bin/chromium /usr/bin/google-chrome \
    && ln -s /usr/bin/chromium /usr/bin/chrome \
    && (test -f /usr/bin/chromedriver || ln -s /usr/lib/chromium/chromedriver /usr/bin/chromedriver) \
    && chromedriver --version

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
