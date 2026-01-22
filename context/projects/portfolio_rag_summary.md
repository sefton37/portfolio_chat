# Kellogg Brengel Portfolio Repository - RAG Summary

## Repository Overview
**URL**: https://github.com/sefton37/portfolio  
**Purpose**: Personal portfolio website at kellogg.brengel.com  
**Core Philosophy**: "The medium is the message" - the site's construction demonstrates the technical depth and judgment it claims to represent

## Key Philosophical Principles

### Design as Demonstration
- Every technical choice is intentional and serves as proof of competency
- The code itself is portfolio-worthy; viewing source reveals craftsmanship
- What's deliberately absent matters as much as what's present
- No WordPress, page builders, hero carousels, stock photography, or unnecessary complexity

### Intentional Minimalism
- "Confidence lives in what you don't fill" - generous whitespace philosophy
- Typography-forward design using Inter (body) and JetBrains Mono (accents)
- Dark mode default with toggle
- Single-scroll narrative: no separate pages, the scroll IS the navigation
- Target: <1s meaningful paint, 100 Lighthouse scores

## Technical Architecture

### Core Stack
- **Framework**: Astro - chosen for static HTML output, zero JavaScript by default
- **Styling**: Tailwind CSS - utility-first, no custom CSS debt
- **Hosting**: Self-hosted on hardened DigitalOcean VPS (~$6/month)
- **Web Server**: nginx with hardened configuration
- **SSL**: Let's Encrypt (automated, free)
- **Deployment**: Git push with post-receive hook

### Why These Choices Matter
| Choice | Demonstrates |
|--------|-------------|
| Astro over React/Next | Understanding of appropriate tool selection, performance priority |
| Self-hosted VPS | Infrastructure competence, not just "I can use Vercel" |
| No CMS/database | Security awareness, minimal attack surface |
| Hand-authored with Claude Code | Code quality as portfolio piece |
| Self-hosted AI backend | ML infrastructure skills, cost efficiency |

### Site Structure
```
src/
├── layouts/Layout.astro       # Base HTML, meta, fonts
├── components/
│   ├── Hero.astro            # Name, title, pitch
│   ├── BentoGrid.astro       # Work samples container
│   ├── BentoCard.astro       # Project cards
│   ├── Chat.astro            # AI assistant interface
│   └── Footer.astro          # Contact + colophon
├── pages/index.astro         # Single-page flow
├── content/projects/         # Markdown project files
└── styles/global.css         # Tailwind + custom properties
```

## Security Posture

### VPS Hardening
- SSH key-only authentication (passwords disabled)
- Non-standard SSH port
- UFW firewall (only ports 80, 443, SSH open)
- Fail2ban monitoring
- Automatic security updates
- Hardened nginx headers
- No database, PHP, or attack surface beyond static files

### AI Integration Security
- Connects to home-hosted Mistral instance
- Cloudflare Tunnel (no open home ports)
- Rate-limited API endpoint
- No sensitive biographical data in model context

## AI Chat Component Philosophy

### "Style Distillation" Approach
The chat demonstrates Kel's capabilities while protecting privacy through:

1. Personal writings analyzed by separate AI
2. Voice characteristics extracted (cadence, philosophy, humor)
3. **Biographical facts explicitly stripped**
4. Essence distilled into system prompt
5. Mistral configured with voice-only prompt

**Result**: Visitors interact with something that feels like talking to Kel without the AI being able to recall or repeat private information.

### Purpose
- Demonstrates claimed AI/ML skills in practice
- Self-hosted infrastructure proves capability
- Near-zero ongoing costs
- Interactive proof of competence

## Content Strategy

### Single-Scroll Narrative
1. **Who**: Name, title, one sentence
2. **What**: Bento grid of selected work
3. **Proof**: AI chat demonstrates the claim
4. **Connect**: Minimal footer with contact

**Key Decision**: No separate "About" page, no blog (unless it earns its place), no traditional navigation

### Design Principles
- **Bento grid layout**: Asymmetric cards, very 2024-2025 aesthetic
- **Subtle motion**: Scroll-triggered reveals, nothing gratuitous
- **Instant load**: Performance as feature
- **Typography-forward**: Font is the design
- **Dark mode default**: Current aesthetic, easier on eyes

## Deployment Process

### Git-Based Workflow
```bash
git push production main
```

### Post-Receive Hook Automation
1. Pulls latest code
2. Runs `npm run build`
3. Copies `dist/` to nginx serving directory
4. Reloads nginx if needed

**Philosophy**: No vendor lock-in, full transparency, demonstrates ops skills

## Development Commands
```bash
npm install        # Install dependencies
npm run dev        # Start dev server
npm run build      # Build for production
npm run preview    # Preview production build
```

## Key Differentiators

### What Makes This Portfolio Different
1. **Infrastructure as Resume**: Self-hosting demonstrates ops capabilities
2. **Code as Portfolio**: View-source reveals craftsmanship
3. **AI Integration**: Live demonstration of ML infrastructure skills
4. **Security Conscious**: Hardened VPS, minimal attack surface
5. **Cost Efficient**: ~$6/month hosting, near-zero AI costs
6. **No Vendor Lock-in**: Full control, transparent deployment

### What's Deliberately Absent
- WordPress / page builders
- Database / CMS
- Heavy JavaScript frameworks
- Stock photography
- Hero carousels
- Blog (unless it earns its place)
- Separate navigation (scroll is navigation)
- About page (story told through scroll)

## Professional Context

### Target Audience
People who might want to meet with or hire Kellogg Brengel

### Value Proposition
The site doesn't just claim technical competence - it proves it through:
- Architecture decisions
- Security implementation
- Performance optimization
- Infrastructure management
- AI/ML deployment
- Code quality

### Tagline Philosophy
"Built with intention. View source encouraged."

## Integration with Kel's Broader Work

### Connection to ReOS
- Demonstrates natural language interface philosophy
- Shows AI integration approach (style without biography)
- Exemplifies "sovereignty through self-hosting"
- Proves local AI deployment capabilities

### Alignment with Kel's Values
- **Transparency**: Open invitation to view source
- **Sovereignty**: Self-hosted, no vendor dependence
- **Intentionality**: Every choice justified and purposeful
- **Minimal Complexity**: No feature without earned place
- **Security**: Hardened infrastructure, minimal attack surface

## Technical Competencies Demonstrated

### Direct Evidence
- Static site generation (Astro)
- Modern CSS architecture (Tailwind)
- Linux server administration
- Web server configuration (nginx)
- SSL/TLS management (Let's Encrypt)
- Firewall configuration (UFW)
- Security hardening (Fail2ban, SSH configuration)
- Git-based deployment
- ML model hosting (Mistral)
- Cloudflare Tunnel configuration
- API endpoint design
- Performance optimization

### Implied Skills
- Infrastructure as Code thinking
- Cost optimization
- Security-first architecture
- Performance engineering
- User experience design
- Content strategy
- Technical writing

## RAG Query Optimization

### Common Query Patterns
- "Tell me about Kel's portfolio site"
- "What technologies does Kel use?"
- "How does Kel host his portfolio?"
- "What security measures does Kel implement?"
- "How does the AI chat work on Kel's site?"
- "Why did Kel choose Astro?"
- "What's the philosophy behind Kel's portfolio?"

### Key Retrieval Concepts
- Self-hosting, infrastructure competence, security hardening
- Astro, Tailwind, static site generation
- Minimal complexity, intentional design
- AI integration, Mistral, style distillation
- Performance optimization, Lighthouse scores
- Git-based deployment, DigitalOcean VPS
- "Medium is the message" philosophy
- View source encouragement

## Summary Statement

Kellogg Brengel's portfolio at kellogg.brengel.com is a self-hosted Astro static site that demonstrates technical competence through its architecture rather than just claiming it. Built with Claude Code and hosted on a hardened DigitalOcean VPS, the site features self-hosted AI chat (Mistral) that embodies Kel's communication style without biographical data. Every technical choice - from Astro for static generation to minimal attack surface security - serves as proof of infrastructure, development, and ML deployment capabilities. The philosophy: "the medium is the message" - the way the site is built demonstrates the judgment and technical depth it represents. Cost: ~$6/month hosting, near-zero AI costs. Design: typography-forward, dark mode default, single-scroll narrative with bento grid layout. Security: hardened VPS, key-only SSH, UFW firewall, no unnecessary complexity. The code itself is portfolio-worthy, with an explicit invitation to view source.
