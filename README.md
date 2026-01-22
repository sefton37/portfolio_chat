# Portfolio Chat

A zero-trust, defense-in-depth LLM inference pipeline for kellogg.brengel.com.

## Overview

This system powers the AI chat feature on Kellogg Brengel's portfolio website. It runs entirely on local hardware (no cloud inference), implementing multiple security layers to safely expose an LLM to the public internet.

**Key Features**:
- 9-layer security pipeline
- Cheap models for routing/validation, capable models for generation
- Zero trust architecture (every layer assumes previous layers failed)
- Multi-turn conversation support (with TTL expiration and turn limits)
- Tool calling for contact messages (MCP-style)
- IP spoofing prevention via trusted proxy validation
- Cloudflare Tunnel integration (no open ports)

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full pipeline design.

See [SECURITY.md](./SECURITY.md) for threat model and defenses.

## Requirements

### Hardware
- 16GB+ RAM recommended
- GPU optional but improves response time
- Tested on: AMD Threadripper, 256GB RAM, RTX 4070

### Software
- Python 3.11+
- Ollama (for local LLM inference)
- cloudflared (for tunnel to Cloudflare)

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/sefton37/portfolio_chat.git
cd portfolio_chat

# 2. Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Pull required models
ollama pull qwen2.5:0.5b   # For classification
ollama pull llama3.2:1b     # For intent parsing
ollama pull mistral:7b      # For generation

# 4. Copy environment template
cp .env.example .env
# Edit .env with your configuration

# 5. Run the server
python -m portfolio_chat.server

# Server starts on http://localhost:8000
```

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run security tests
pytest tests/security/

# Run with hot reload
uvicorn portfolio_chat.server:app --reload

# Type checking
mypy portfolio_chat/

# Linting
ruff check portfolio_chat/
```

## Project Structure

```
portfolio_chat/
├── src/
│   └── portfolio_chat/
│       ├── __init__.py
│       ├── server.py           # FastAPI application
│       ├── config.py           # Configuration management
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── orchestrator.py # Main pipeline coordinator
│       │   ├── layer0_network.py
│       │   ├── layer1_sanitize.py
│       │   ├── layer2_jailbreak.py
│       │   ├── layer3_intent.py
│       │   ├── layer4_route.py
│       │   ├── layer5_context.py
│       │   ├── layer6_generate.py
│       │   ├── layer7_revise.py
│       │   ├── layer8_safety.py
│       │   └── layer9_deliver.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── ollama_client.py
│       │   └── model_config.py
│       ├── conversation/
│       │   ├── __init__.py
│       │   └── manager.py      # Multi-turn conversation handling
│       ├── contact/
│       │   ├── __init__.py
│       │   └── storage.py      # Contact message storage
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── definitions.py  # Tool schemas
│       │   └── executor.py     # Tool execution
│       └── utils/
│           ├── __init__.py
│           ├── logging.py
│           ├── rate_limit.py
│           └── semantic_verify.py  # Hallucination detection
├── context/                     # Domain context documents
│   ├── professional/
│   ├── projects/
│   ├── hobbies/
│   ├── philosophy/
│   └── meta/
├── prompts/                     # System and layer prompts
│   ├── system_prompt.md
│   ├── jailbreak_classifier.md
│   ├── intent_parser.md
│   └── safety_checker.md
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   └── e2e/
├── ARCHITECTURE.md
├── SECURITY.md
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

## API Endpoints

### POST /chat

Send a message to the chat system.

**Request**:
```json
{
  "message": "What's Kel's experience with Power BI?"
}
```

**Response**:
```json
{
  "success": true,
  "response": {
    "content": "Kel has extensive experience with Power BI...",
    "domain": "PROFESSIONAL"
  },
  "metadata": {
    "response_time_ms": 1234,
    "request_id": "abc123"
  }
}
```

### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "models_loaded": true,
  "uptime_seconds": 3600
}
```

## Configuration

Environment variables (`.env`):

```bash
# Server
CHAT_API_PORT=8000
CHAT_API_HOST=127.0.0.1  # Default: localhost for safety

# Ollama
OLLAMA_HOST=http://localhost:11434

# Models
CLASSIFIER_MODEL=qwen2.5:0.5b
ROUTER_MODEL=llama3.2:1b
GENERATOR_MODEL=mistral:7b
VERIFIER_MODEL=qwen2.5:0.5b
EMBEDDING_MODEL=nomic-embed-text

# Rate Limiting
RATE_LIMIT_PER_IP_PER_MINUTE=10
RATE_LIMIT_PER_IP_PER_HOUR=100
RATE_LIMIT_GLOBAL_PER_MINUTE=1000

# Conversation
MAX_TURNS=10                    # Max conversation turns
CONVERSATION_TTL_SECONDS=1800   # 30 minute timeout
MAX_HISTORY_TOKENS=4000         # Max tokens in history

# Security
MAX_INPUT_LENGTH=2000
MAX_REQUEST_SIZE=8192
REQUEST_TIMEOUT_SECONDS=30
TRUSTED_PROXIES=                # Comma-separated IPs (e.g., Cloudflare)
METRICS_ENABLED=false           # Set true to expose /metrics

# Logging
LOG_LEVEL=INFO
```

## Deployment

### With Cloudflare Tunnel

1. Install cloudflared:
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

2. Create tunnel:
```bash
cloudflared tunnel login
cloudflared tunnel create portfolio-chat
```

3. Configure tunnel (`~/.cloudflared/config.yml`):
```yaml
tunnel: <your-tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: chat-api.brengel.com
    service: http://localhost:8000
  - service: http_status:404
```

4. Route DNS:
```bash
cloudflared tunnel route dns portfolio-chat chat-api.brengel.com
```

5. Run tunnel:
```bash
cloudflared tunnel run portfolio-chat
```

### Systemd Service

```ini
# /etc/systemd/system/portfolio-chat.service
[Unit]
Description=Portfolio Chat API
After=network.target ollama.service

[Service]
Type=simple
User=portfolio_chat
WorkingDirectory=/opt/portfolio_chat
ExecStart=/opt/portfolio_chat/venv/bin/python -m portfolio_chat.server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Contributing

This is a personal project, but issues and suggestions are welcome.

## License

MIT
