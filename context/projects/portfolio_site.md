# Portfolio Website Project

## Overview

This portfolio website at kellogg.brengel.com showcases my professional work and includes an AI-powered chat system for visitors to learn more about my background.

## Technical Architecture

### Chat System (This Feature)
The chat system uses a 9-layer zero-trust inference pipeline:

1. **Layer 0 - Network Gateway**: Rate limiting, request validation
2. **Layer 1 - Input Sanitization**: Character normalization, pattern detection
3. **Layer 2 - Jailbreak Detection**: LLM-based injection detection
4. **Layer 3 - Intent Parsing**: Extract topic, question type, entities
5. **Layer 4 - Domain Routing**: Route to appropriate knowledge domain
6. **Layer 5 - Context Retrieval**: Fetch relevant information
7. **Layer 6 - Response Generation**: Generate response with main LLM
8. **Layer 7 - Response Revision**: Self-critique and refinement
9. **Layer 8 - Output Safety**: Final safety validation
10. **Layer 9 - Response Delivery**: Format and deliver response

### Technology Stack
- **Backend**: Python, FastAPI
- **LLM**: Ollama (local inference)
- **Models**: qwen2.5:0.5b (classification), llama3.2:1b (routing), mistral:7b (generation)
- **Hosting**: Self-hosted with Cloudflare Tunnel

### Security Considerations
- No open ports on home network
- All traffic through Cloudflare Tunnel
- Multiple layers of input validation
- Fail-closed design philosophy

## Design Philosophy

The security and architecture of this system itself demonstrates technical competence. It's not just a portfolio site - it's a working example of building production-ready AI systems with security as a first-class concern.

---

*Note: This is a placeholder. Expand with more details about the portfolio site.*
