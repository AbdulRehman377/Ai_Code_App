# AI Code Generator (Plan → Code)

A Streamlit application that generates implementation plans and complete codebases from natural language descriptions using Azure OpenAI GPT. Now with intelligent chat, auto-routing, and per-file regeneration capabilities.

## Features

### Core Features
- **Natural Language Input**: Describe what you want to build in plain English
- **Language Selection**: Choose from Python, JavaScript, TypeScript, Go, Java, C#, Rust, or let the AI decide
- **Framework Support**: Optionally specify a framework (FastAPI, Express, Next.js, etc.)
- **Two-Stage Generation**:
  1. **Plan**: AI analyzes your request and creates a structured implementation plan
  2. **Code**: AI generates complete, working code files based on the plan
- **Code Preview**: View all generated files with syntax highlighting
- **Download**: Export all files as a ZIP archive

### New Features (v2.0)

#### 🤖 Auto Mode (Intelligent Routing)
- Single input box where you can type anything
- AI automatically detects your intent:
  - **Chat**: General questions and conversations
  - **Build**: Project generation requests
  - **Regen File**: File modification requests
- Seamlessly routes to the appropriate handler

#### 💬 Chat Mode
- Full conversational interface with chat history
- Context-aware responses (knows about your current project)
- Session memory persists during your Streamlit session

#### 🔄 Per-File Regeneration
- After generating a project, regenerate individual files
- Provide specific instructions for changes
- Updates only the selected file, keeping others intact
- Maintains project consistency

#### 🧠 Session Memory
- Conversation history stored in `st.session_state`
- Build context (plan, files) persists across interactions
- Memory is volatile (clears on session end, no database)

#### ▶️ Sandbox Execution
- Run generated Python and Node.js CLI apps in isolated Docker containers
- Capture stdout, stderr, and exit code
- Automatic timeout (5 minutes) and resource limits
- Safe by design: no host mounts, network disabled during execution
- Containers destroyed immediately after execution

**Supported for execution:**
- Python ✅
- Node.js / JavaScript ✅

**NOT supported for execution:**
- React, Vue, Angular (UI frameworks)
- Web servers (Express with long-running servers)
- Other languages (Go, Java, etc.)

#### 🌐 Preview Hosting (NEW!)
- **Live preview** for web applications with exposed ports
- Run apps in Docker with an accessible URL (`http://localhost:{port}`)
- **Interactive preview** - interact with your app in the browser
- **15-minute TTL** (configurable) - containers auto-destroy after timeout
- **Manual stop** - stop previews anytime
- **Container logs** - view real-time logs from the container

**Supported for preview:**
- Python: FastAPI ✅, Flask ✅, Django ✅, Streamlit ✅, Gradio ✅
- Node.js: Express ✅, Next.js ✅, React ✅, Vue ✅, Angular ✅

**How it works:**
1. Click "Start Preview" after generating a web app
2. Container starts with port exposed
3. Access your app at the provided URL
4. Interact with your app in the browser
5. Container auto-destroys after TTL expires (or stop manually)

## Requirements

- Python 3.9+
- Azure OpenAI API access
- **Docker** (for sandbox execution - must be installed and running)

## Setup

1. **Clone or navigate to the project directory**

2. **Create a `.env` file** in the project root with your Azure OpenAI credentials:

```env
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

See `.env.example` for a template.

3. **Install dependencies**:

```bash
pip install -r requirements.txt
```

## Running the App

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

## How It Works

### Architecture

The application uses a LangGraph-based state machine for intelligent routing:

```
User Input → Intent Router → Chat Node (conversation)
                          → Plan Node → Code Node (project generation)
                          → Regen File Node (file modification)
```

### Modes

#### 🤖 Auto Mode
1. Type any message in the input box
2. AI classifies your intent automatically
3. Routes to appropriate handler:
   - Chat questions → conversational response
   - Build requests → plan + code generation
   - File updates → single file regeneration

#### 💬 Chat Mode
1. Pure conversational interface
2. Chat history displayed in feed format
3. Context-aware (knows about your current project)
4. Use this for Q&A, explanations, or guidance

#### 🔨 Build Mode
1. Enter your project description
2. Select language/framework preferences
3. Click "Generate Project"
4. View plan and generated code
5. Download as ZIP
6. Optionally regenerate individual files

### File Regeneration

After generating a project:
1. Go to the "Regenerate" tab
2. Select the file you want to modify
3. Enter your instructions (e.g., "Add error handling", "Use type hints")
4. Click "Regenerate Selected File"
5. The file is updated while preserving other files

## Project Structure

```
.
├── app.py                          # Main Streamlit application
├── src/
│   ├── __init__.py
│   ├── config.py                   # Environment configuration
│   ├── schemas.py                  # Pydantic data models
│   ├── state.py                    # LangGraph state definitions
│   ├── graph.py                    # LangGraph implementation
│   ├── orchestrator.py             # Generation pipeline
│   ├── utils.py                    # Utility functions
│   ├── llm/
│   │   ├── __init__.py
│   │   └── azure_openai_client.py  # Azure OpenAI client
│   ├── prompts/
│   │   ├── plan_system.txt         # Prompt for planning
│   │   ├── code_system.txt         # Prompt for code generation
│   │   ├── intent_system.txt       # Prompt for intent classification
│   │   ├── chat_system.txt         # Prompt for chat responses
│   │   └── regen_file_system.txt   # Prompt for file regeneration
│   └── sandbox/                    # NEW! Sandbox execution & preview
│       ├── __init__.py
│       ├── executor.py             # Run code & capture output
│       ├── preview.py              # Preview hosting with URLs
│       └── registry.py             # Container lifecycle management
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── .gitignore
└── README.md                       # This file
```

## Session Memory

Memory is stored in Streamlit's `st.session_state`:

- `chat_history`: List of conversation turns
- `last_plan`: Most recent generated plan
- `last_codebundle`: Most recent generated code files
- `last_build_query`: The query used for the last build
- `last_intent`: The last detected intent

**Note**: Memory is volatile and only persists during the active browser session. Refreshing the page or closing the browser will clear the memory.

## Notes

- **Sandbox Execution**: Generated Python and Node.js CLI code can be executed in isolated Docker containers. See the "Run" tab after code generation.
- **Preview Hosting**: Web applications (FastAPI, Flask, Express, etc.) can be previewed with live URLs. See the "Preview" tab after code generation.
- **Container Registry**: Running preview containers are tracked in `.preview_registry.json` for TTL management.
- **JSON Parsing**: The app includes robust JSON parsing with retry logic and repair fallbacks.
- **LangGraph**: Uses LangGraph for deterministic state-based routing (no vector DB, no retrievers).
- **Dependencies**: streamlit, openai, pydantic, langgraph, docker.

## Troubleshooting

### Configuration Error
If you see a configuration error, ensure your `.env` file:
- Exists in the project root
- Contains all required variables
- Has valid Azure OpenAI credentials

### JSON Parse Errors
If the AI returns malformed JSON, the app will:
1. Automatically retry with a clarified prompt (up to 2 retries)
2. Attempt to repair common JSON issues
3. Show an error if all attempts fail

Try simplifying your request or regenerating.

### Content Filter Issues
Azure OpenAI has content filtering that may occasionally block certain prompts. If you encounter this:
- Try rephrasing your request
- Use simpler, more direct language

## License

MIT
