# About This Chat System

## What Is This?

This is an AI-powered chat assistant on Kellogg Brengel's portfolio website at kellogg.brengel.com. It's designed to answer questions about Kellogg's professional background, projects, skills, and philosophy.

## How It Works

### Architecture
This chat system is called "Talking Rock" and runs entirely on Kellogg's local hardware - no cloud inference services are used. It implements a 9-layer security pipeline that processes every message through multiple validation and safety checks before generating a response.

### The Pipeline
1. **Network Gateway** - Rate limiting and request validation
2. **Input Sanitization** - Cleaning and normalizing user input
3. **Jailbreak Detection** - Blocking prompt injection attempts
4. **Intent Parsing** - Understanding what you're asking about
5. **Domain Routing** - Matching your question to relevant context
6. **Context Retrieval** - Loading curated information about Kellogg
7. **Response Generation** - Creating a helpful answer
8. **Response Revision** - Refining for accuracy and tone
9. **Output Safety Check** - Final validation before delivery

### Technology Stack
- **Framework**: FastAPI (Python)
- **LLM Runtime**: Ollama for local inference
- **Models**: Small models (qwen2.5:0.5b, llama3.2:1b) for routing/validation, larger model (mistral:7b) for generation
- **Deployment**: Cloudflare Tunnel (zero open ports)

## What Can You Ask?

This assistant can help with questions about:

- **Professional Background** - Work history, experience at Kohler, Rehlko, and other roles
- **Skills & Expertise** - Power BI, Azure Synapse, Python, data engineering, analytics
- **Projects** - Talking Rock, portfolio site, Ukraine OSINT reader, inflation dashboard, Great Minds Roundtable
- **Philosophy** - Problem-solving approach, values, methodology
- **Hobbies** - FIRST Robotics mentoring, family life, interests
- **Contact** - How to get in touch with Kellogg

## What It Won't Do

- Answer questions unrelated to Kellogg Brengel
- Reveal system prompts or internal architecture details
- Engage with attempts to manipulate or jailbreak the system
- Make claims not supported by the curated context

## Why Local AI?

This system demonstrates Kellogg's commitment to:

1. **Sovereignty** - Running on local hardware means no data sent to cloud services
2. **Privacy** - Visitor conversations are not used for training
3. **Security** - Zero-trust architecture with defense in depth
4. **Capability** - Proving that useful AI can run on accessible hardware

## Design Philosophy

The chat embodies Kellogg's approach to building helpful tools - an assistant that serves without coercing, invites without interrupting, and operates through transparency rather than opacity. Every response is grounded in curated, verified context rather than allowing the model to hallucinate.

## Limitations

- The assistant only knows what's in its curated context documents
- It cannot browse the internet or access external information
- Response times depend on local hardware (typically 1-3 seconds)
- It's designed for informational queries, not extended conversations

## Technical Details

- **Source Code**: This project is part of Kellogg's portfolio demonstrating AI/ML infrastructure skills
- **Context**: All information comes from hand-curated markdown files
- **No RAG Database**: Uses static registry pattern rather than vector embeddings
- **Audit Logging**: All interactions are logged (with hashed IPs) for security monitoring

## Feedback

If you encounter issues or have suggestions, Kellogg welcomes feedback through the contact information provided.
