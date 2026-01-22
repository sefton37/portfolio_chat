# Projects Overview

Kellogg Brengel's projects demonstrate his approach to building software: sovereignty over dependence, transparency over opacity, and thoughtful architecture over quick solutions.

## Featured Projects

### Talking Rock
**Local-First AI Assistant Framework**

A three-agent AI system designed to run on consumer hardware (8GB RAM, no GPU required). Embodies the "No One" philosophy - AI that serves without coercing, operates through invitation rather than extraction.

- **CAIRN**: Attention management agent for life organization
- **ReOS**: Natural language Linux system control
- **RIVA**: Code verification engine (frozen pending hardware evolution)

Key insight: Local inference is essentially free after model download, enabling verification passes that cloud services can't afford at scale.

[Repository](https://github.com/sefton37/talking_rock)

### Portfolio Website & Chat
**kellogg.brengel.com**

Self-hosted portfolio site demonstrating "the medium is the message" - the site's construction proves the technical depth it claims to represent.

- Astro static site with Tailwind CSS
- Self-hosted on hardened DigitalOcean VPS (~$6/month)
- 9-layer security pipeline for AI chat
- Cloudflare Tunnel integration (zero open ports)

Philosophy: Infrastructure as resume. View source encouraged.

### Ukraine OSINT Intelligence Reader
**Intelligence Briefing Interface**

An OSINT aggregator designed for analytical workflows, not casual browsing. Structures information the way intelligence flows to decision-makers.

- AI-generated executive summaries synthesizing multiple sources
- Priority-coded articles (Critical/High/Medium)
- Credible institutional sources only (ISW, CSIS, RUSI)
- Theater map with operational context

Demonstrates intelligence analysis tradecraft applied to open-source monitoring.

### Total Cost of Inflation Dashboard
**Economic Data Visualization**

Interactive dashboard revealing the true cost of inflation on American households since 1971 (end of gold standard).

- Custom composite inflation index weighted by actual household spending
- Percentile-based analysis (10th through 90th)
- Personal calculator for individual assessment
- Three-act narrative: macro picture → personal impact → structural barriers

Core finding: Only the 90th percentile has accumulated wealth faster than true inflation.

### Great Minds Roundtable
**AI-Powered Intellectual Debate Simulator**

Web application simulating debates among history's political theorists, economists, and philosophers. Users pose questions and watch AI-generated voices from different schools of thought engage in structured debate.

- 15+ thinkers from Locke to Foucault, Keynes to Hayek
- Waterfall conversation pattern for genuine dialogue
- Real quotes with verified source citations
- Custom thinker creation

Educational tool demonstrating how complex questions benefit from multiple intellectual frameworks applied simultaneously.

## Technical Themes

### Sovereignty Through Self-Hosting
Every project emphasizes local control and user autonomy:
- No cloud dependencies for core functionality
- Data stays on user's hardware
- No vendor lock-in

### Security as Architecture
Security isn't a feature, it's a structural commitment:
- Zero-trust design patterns
- Defense in depth
- Minimal attack surfaces

### Thoughtful Constraints
Choosing appropriate tools over powerful tools:
- Small models when they suffice
- Static sites over dynamic when possible
- Simplicity over premature abstraction

### Transparency
Code as communication:
- View source encouraged
- Open source by default
- Documentation as first-class citizen

## Development Philosophy

Kellogg's projects follow a consistent methodology:

1. **Intent** - Establish clear, verifiable objectives
2. **Contract** - Define scope, constraints, success criteria
3. **Decompose** - Break into verifiable components
4. **Build** - Develop with transparency built in
5. **Verify** - Test against intent at each step
6. **Integrate** - Assemble only when verification confirms alignment

This produces not just solutions but documentation of *why* decisions were made.
