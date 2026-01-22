# Great Minds Roundtable

## Project Overview

**Great Minds Roundtable** is a web application created by Kellogg Brengel that simulates intellectual debates among history's most influential political theorists, economists, and philosophers. Users pose questions on any topic—power, governance, economics, rights, technology, conflict—and watch as AI-generated voices representing different schools of thought engage in structured debate.

The app is built as a single-file React artifact using the Anthropic API (Claude) to generate responses in the authentic voice of each thinker.

## Core Concept & Philosophy

The central insight is that complex questions benefit from multiple intellectual frameworks applied simultaneously. Rather than getting one AI response, users see how a neorealist, an institutionalist, a postcolonial theorist, and a classical liberal might each approach the same question—then watch them respond to each other.

Kellogg's design philosophy treats the default question as a "seed" (like in Minecraft's procedural generation)—it sets the stage and signals the creator's intent. The default question centers on the Declaration of Independence's assertion of equality and unalienable rights, asking how an AI-driven society can remain congruent with these principles.

The app acknowledges that responses may contain anachronisms, as 17th-19th century frameworks are applied to modern concepts like AI. This is intentional—the value is in seeing how foundational principles translate (or tension) with contemporary challenges.

## Technical Architecture

### State Management
The app uses a proper **state machine** implemented with `useReducer`:
- **Phases**: `IDLE → ASKING → COUNTER_SELECT → COUNTER_USER/COUNTER_CHAMPION → REBUTTALS → COUNTER_SELECT (loop)`
- **Actions**: Explicit action types for all state transitions
- All debate logic flows through the reducer—no scattered state mutations

### Key Technical Decisions

1. **Waterfall Conversation Pattern**: Each thinker receives the full context of what previous thinkers said, creating genuine dialogue rather than isolated responses.

2. **Quote Citation System**: Each response includes a real quote from the thinker's actual writings. The app then performs a web search to find a reputable source URL for citation.

3. **Sequential Quote Search Queue**: To avoid API rate limits, quote searches are queued and processed sequentially with delays, while the main conversation continues.

4. **Abort Controller Pattern**: All API calls can be cancelled when users start new questions or reset, preventing stale responses.

5. **Input Sanitization**: User input is sanitized before inclusion in prompts (basic prompt injection protection).

### Code Organization (Single-File Constraint)
Despite being a single file (artifact limitation), the code is organized into clear sections:
```
CONSTANTS
THINKER DEFINITIONS
STATE MACHINE (phases, actions, reducer)
UTILITIES (parsing, color generation, transcript building)
API LAYER (centralized API calls)
CUSTOM HOOKS (quote search queue)
COMPONENTS (ThinkerButton, QuoteBlock, ResponseCard, AddThinkerModal)
MAIN COMPONENT
```

## Thinker Roster

### International Relations
- **Kenneth Waltz** (Neorealism) - anarchy, state survival, structural constraints
- **Robert Keohane** (Institutionalism) - cooperation, interdependence, regimes
- **Hedley Bull** (English School) - international society, order vs justice
- **Alexander Wendt** (Constructivism) - social construction, identity
- **Hans Morgenthau** (Classical Realism) - human nature, power politics
- **Robert Cox** (Critical Theory) - hegemony, ideology critique

### Economics
- **John Maynard Keynes** (Keynesian) - aggregate demand, government intervention
- **Friedrich Hayek** (Classical Liberal) - spontaneous order, individual liberty

### Development & Capabilities
- **Amartya Sen** (Capability Approach) - substantive freedoms, development as freedom
- **Martha Nussbaum** (Human Capabilities) - dignity, emotions in ethics

### Heterodox & Institutional
- **Ha-Joon Chang** (Heterodox Economics) - industrial policy, challenging orthodoxy
- **Elinor Ostrom** (Commons Governance) - polycentricity, local knowledge

### Postcolonial & Revolutionary
- **Frantz Fanon** (Postcolonial) - colonial violence, decolonization of mind
- **Rosa Luxemburg** (Revolutionary Left) - capitalism's contradictions, democracy from below

### Kellogg's Favorites (Default Selection)
- **Thomas Paine** (Revolutionary Liberal) - natural rights, common sense for common people
- **John Locke** (Classical Liberalism) - natural rights, consent of governed, labor theory of property
- **Michel Foucault** (Post-Structuralism) - power/knowledge, suspicious of apparent freedoms
- **Charles Krauthammer** (Neoconservatism) - American power, democratic realism

Users can also **create custom thinkers** by providing a name and school of thought. The app auto-generates an appropriate prompt based on that thinker's known works.

## Features

### Core Debate Flow
1. User poses a question (or uses default/suggestions/headlines)
2. Selected thinkers respond in sequence, each aware of previous responses
3. User can challenge via "Enter the Debate" (write counter-argument) or "Pick a Champion" (select a thinker to challenge others)
4. All participants respond to the challenge in waterfall fashion
5. Debate can continue indefinitely with new rounds

### Champion Selection
Users can pick a champion from:
- Current debate participants
- Any thinker from the full roster
- A newly created custom thinker

New voices joining mid-debate receive special prompts acknowledging they're entering an ongoing discussion.

### Quote Citations
Each response includes:
- The thinker's perspective (2-3 sentences, first person)
- A real quote from their writings relevant to the topic
- Source citation (book/article, year)
- Hyperlinked URL to reputable source (when found via web search)

### Presets
- **Kellogg's Favorites**: Paine, Locke, Foucault, Krauthammer
- **IR Classic**: Waltz, Keohane, Bull, Wendt
- **Economic Debate**: Keynes, Hayek, Sen, Chang
- **Maximum Diversity**: Sen, Ostrom, Fanon, Hayek

### Headlines Feature
"From Headlines" button searches current news and generates 4 thought-provoking questions based on current events.

### Save Transcript
Copies full debate transcript to clipboard, including:
- Original question
- All responses with quotes and citations
- All rebuttals marked as champion/rebuttal
- Links to sources

## Design Principles

1. **Educational, Not Authoritative**: Clear disclaimer that these are AI simulations, not actual views.

2. **Anachronism-Aware**: Historical frameworks applied to modern concepts will produce anachronisms—this is acknowledged and intentional.

3. **Period-Appropriate Language**: Prompts guide thinkers toward authentic vocabulary (e.g., Locke speaks of "exchange of commodities" rather than "markets").

4. **Continuous Debate**: No artificial endpoint—users can continue challenging and bringing in new voices indefinitely.

5. **Accessible Complexity**: Social-media-style card UI makes dense intellectual content scannable and digestible.

## Suggested Questions (Built-in)

1. "Is democracy compatible with the concentration of wealth, or does economic inequality inevitably corrupt political equality?"

2. "When institutions fail to protect rights, at what point does civil disobedience become not just justified but obligatory?"

3. "Can a nation maintain both open borders and a robust welfare state, or are these goals fundamentally in tension?"

## Development Context

This project was developed iteratively through conversation, with Kellogg providing direction and Claude implementing. Key evolution points:

1. Started as a simple chat interface concept
2. Added waterfall conversation pattern for genuine dialogue
3. Expanded thinker roster based on gaps in traditional IR education
4. Added quote citation system for grounding in real texts
5. Refactored from 15+ useState calls to proper state machine
6. Added continuous debate capability
7. Implemented rate-limit-safe quote search queue
8. Added custom thinker creation

The code reflects a balance between "artifact constraints" (single file, no external state management) and "production quality" (clean architecture, separation of concerns, explicit state machine, proper error handling).

## Key Quotes About the Project

On the default question as creative framing:
> "Think of it as if this was a game of Minecraft, I'm picking the seed for the possible path of procedural generation by asking a leading question."

On anachronisms:
> "Ultimately it is ok that anachronisms are ok, it's kind of intended, but something to be mindful of as we continue."

On alpha tester feedback about Locke using "markets":
> Led to research confirming Locke used "vent and quantity" terminology, and prompt updates for period-appropriate language.

## Technical Stack

- React (functional components, hooks)
- useReducer for state machine
- Anthropic API (Claude Sonnet 4) for generation
- Web Search tool for quote citations and headline generation
- Tailwind CSS for styling
- No external dependencies beyond what's available in Claude artifacts

## Future Considerations

- Persistence via `window.storage` API for custom thinkers
- Error boundaries for graceful failure
- TypeScript for type safety (artifact constraint)
- More period-appropriate language guidance for all historical thinkers
