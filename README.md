# AI Agent System

This project contains a complete functional AI agent system that uses local LLMs (specifically Ollama) to function as an autonomous software engineer.

## Overview

The system is designed to:
- Generate complete, functional Python code from natural language prompts
- Act as an autonomous software engineer capable of building complex applications
- Work with local LLM models through the Ollama API
- Provide a GUI interface for interaction

## Key Components

### Main Agent Files
- `run_agent.py` - Core agent execution logic that interfaces with Ollama
- `run_gui.py` - Graphical user interface for the AI agent
- `test_agent.py` - Testing framework to verify agent functionality
- `complex_test.py` - Advanced testing for complex code generation

### Environment Setup
- `agent-env/` - Python virtual environment with required dependencies
- The system requires Ollama to be running locally with models like `llama3.2:latest`

## Functionality Demonstrated

The AI agent has been tested and proven to:
1. Successfully connect to local Ollama instance
2. Generate complete, functional Python applications from prompts
3. Handle complex software engineering tasks
4. Stream responses from the LLM in real-time

## Testing Results

The system was successfully tested with:
- Basic connectivity test showing "Connection Established!" 
- Complex code generation test that created a full Finance Tracker application
- Streaming response handling for long-running tasks

## Usage

1. Ensure Ollama is running locally with required models
2. Run `python test_agent.py` to verify connection
3. Run `python complex_test.py` to test code generation
4. Run `python run_gui.py` to start the GUI interface

The agent can be used to automatically generate complete software solutions from natural language descriptions.