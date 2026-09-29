#!/data/data/com.termux/files/usr/bin/bash
set -e
echo "📦 Updating Termux packages..."
pkg update -y && pkg upgrade -y
pkg install -y python git nano binutils openssl libffi tur-repo

echo "🐍 Installing Python 3.10..."
pkg install -y python3.10

echo "📁 Creating virtual environment..."
python3.10 -m venv venv
source venv/bin/activate

echo "📦 Installing pre-compiled pydantic-core (Android)..."
pip install "pydantic-core==2.41.5" --extra-index-url https://eutalix.github.io/android-pydantic-core/ --only-binary=:all:

echo "📦 Installing remaining packages..."
pip install pydantic==2.12.5 --no-deps
pip install typing-inspection annotated-types typing-extensions
pip install aiogram --no-deps
pip install aiofiles aiohttp magic-filter certifi
pip install turso-serverless==0.1.0 python-dotenv==1.0.1
pip install Flask==3.0.3 gunicorn==22.0.0 requests==2.32.3

echo "✅ Setup complete."
echo "Next: create .env file, then run: python bot.py"
