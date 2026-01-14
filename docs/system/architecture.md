# Architecture

This document explains the high-level architecture of Project Argo.

It focuses on structure, boundaries, and responsibilities rather than implementation details.

## Model Execution

Argo communicates with a persistent Ollama server over HTTP. Models are not spawned per request. Instead, Argo sends prompts to the server, which streams responses back in real-time. This approach eliminates the overhead of spawning subprocesses, improving response speed and efficiency.