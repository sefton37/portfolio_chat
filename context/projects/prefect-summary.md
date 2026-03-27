# Prefect: Server-Side AI Steward

## Overview

Prefect is a server-side AI steward for managing game servers. It provides process management, log monitoring, and command execution with safety guardrails through MCP (Model Context Protocol) and Qt interfaces.

**Repository:** https://github.com/sefton37/Prefect
**Language:** Python
**Status:** Active

## What It Does

Prefect manages game server instances — starting, stopping, monitoring logs, executing commands — with AI-powered assistance. It wraps server administration in safety guardrails so that routine management tasks are handled reliably and dangerous operations require explicit confirmation.

## Key Features

- **Process Management:** Start, stop, restart, and monitor game server processes
- **Log Monitoring:** Real-time log watching with pattern detection for errors, crashes, and anomalies
- **Command Execution:** Safe command interface with guardrails preventing destructive operations
- **MCP Interface:** Exposes server management as MCP tools for AI agent integration
- **Qt Interface:** Desktop GUI for direct server management

## Design Philosophy

Prefect follows the same principles as the rest of Kellogg's work:

- **Safety first:** Destructive operations are guarded, not freely available
- **Transparency:** Every action is logged, every command is auditable
- **Local operation:** Runs on the same hardware as the game servers
- **AI-assisted, not AI-controlled:** The AI suggests and executes with approval, never autonomously

## Connection to Broader Work

Prefect demonstrates the same pattern seen in CAIRN, ReOS, and RIVA — AI as a careful assistant rather than an autonomous agent. The MCP integration shows Kellogg's familiarity with emerging AI tool protocols, and the safety guardrails reflect the same defense-in-depth philosophy used in the portfolio chat's 9-layer pipeline.
