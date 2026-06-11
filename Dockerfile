FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot/ bot/
COPY personas/ personas/
COPY content_config.yaml .

# Create data directory for session and DB
RUN mkdir -p data content/selfies content/videos

# Run the bot
CMD ["python", "-m", "bot.main"]
