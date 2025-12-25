# AI Code Generator

A Streamlit application that generates implementation plans and complete codebases from natural language descriptions using Azure OpenAI GPT. Features intelligent chat, auto-routing, per-file regeneration, and live Docker-based preview hosting.

## ✨ Features

### Core Features
- **Natural Language Input**: Describe what you want to build in plain English
- **Language Selection**: Choose from Python, JavaScript, TypeScript, Go, Java, C#, Rust, or let the AI decide
- **Framework Support**: Optionally specify a framework (FastAPI, Express, React, Next.js, etc.)
- **Two-Stage Generation**:
  1. **Plan**: AI analyzes your request and creates a structured implementation plan
  2. **Code**: AI generates complete, working code files based on the plan
- **Code Preview**: View all generated files with syntax highlighting
- **Download**: Export all files as a ZIP archive

### 🤖 Auto Mode (Intelligent Routing)
- Single input box where you can type anything
- AI automatically detects your intent:
  - **Chat**: General questions and conversations
  - **Build**: Project generation requests
  - **Regen File**: File modification requests
- Seamlessly routes to the appropriate handler

### 💬 Chat Mode
- Full conversational interface with chat history
- Context-aware responses (knows about your current project)
- Session memory persists during your Streamlit session

### 🔄 Per-File Regeneration
- After generating a project, regenerate individual files
- Provide specific instructions for changes
- Updates only the selected file, keeping others intact
- Maintains project consistency

### 🌐 Live Preview Hosting
- **Live preview** for web applications with exposed ports
- Run apps in Docker with an accessible URL (`http://localhost:{port}`)
- **Interactive preview** - interact with your app in the browser
- **Configurable TTL** (5-30 minutes) - containers auto-destroy after timeout
- **Manual stop** - stop previews anytime
- **Container logs** - view real-time logs from the container

**Supported Frameworks:**

| Language | Frameworks |
|----------|------------|
| Python | FastAPI ✅, Flask ✅, Django ✅, Streamlit ✅, Gradio ✅ |
| Node.js | Express ✅, Next.js ✅, React (Vite) ✅, Vue ✅, Angular ✅ |

**How it works:**
1. Generate a web application project
2. Go to the "Preview" tab
3. Click "Start Preview"
4. Wait for dependencies to install (2-5 min for Node.js apps)
5. Access your app at the provided URL
6. Container auto-destroys after TTL expires (or stop manually)

### 🧠 Session Memory
- Conversation history stored in `st.session_state`
- Build context (plan, files) persists across interactions
- Memory is volatile (clears on session end, no database)

## 📋 Requirements

- Python 3.9+
- Azure OpenAI API access
- **Docker** (must be installed and running for preview hosting)

## 🚀 Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd <project-directory>
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

See `.env.example` for a template.

### 5. Ensure Docker is running

```bash
docker --version  # Verify Docker is installed
docker ps         # Verify Docker daemon is running
```

## ▶️ Running the App

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

## 🏗️ Architecture

The application uses a **LangGraph-based state machine** for intelligent routing:

```
User Input → Intent Router → Chat Node (conversation)
                          → Plan Node → Code Node (project generation)
                          → Regen File Node (file modification)
```

### State Flow

```
┌─────────────────┐
│  User Input     │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Intent Router   │ ← Classifies: chat | build | regen_file
└────────┬────────┘
         │
    ┌────┴────┬────────────┐
    ▼         ▼            ▼
┌───────┐ ┌───────┐ ┌────────────┐
│ Chat  │ │ Plan  │ │ Regen File │
│ Node  │ │ Node  │ │   Node     │
└───────┘ └───┬───┘ └────────────┘
              ▼
         ┌───────┐
         │ Code  │
         │ Node  │
         └───────┘
```

## 📁 Project Structure

```
.
├── app.py                          # Main Streamlit application
├── src/
│   ├── __init__.py
│   ├── config.py                   # Environment configuration
│   ├── schemas.py                  # Pydantic data models
│   ├── state.py                    # LangGraph state definitions
│   ├── graph.py                    # LangGraph implementation
│   ├── orchestrator.py             # Generation pipeline wrapper
│   ├── utils.py                    # Utility functions
│   ├── llm/
│   │   ├── __init__.py
│   │   └── azure_openai_client.py  # Azure OpenAI client with retry logic
│   ├── prompts/
│   │   ├── plan_system.txt         # Prompt for planning
│   │   ├── code_system.txt         # Prompt for code generation
│   │   ├── intent_system.txt       # Prompt for intent classification
│   │   ├── chat_system.txt         # Prompt for chat responses
│   │   └── regen_file_system.txt   # Prompt for file regeneration
│   └── sandbox/
│       ├── __init__.py
│       ├── executor.py             # Console app execution
│       ├── preview.py              # Web app preview hosting
│       └── registry.py             # Container lifecycle management
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── .gitignore
└── README.md
```

## 🔧 Usage

### Auto Mode (Recommended)
1. Type any message in the input box
2. AI classifies your intent automatically
3. Routes to appropriate handler

### Chat Mode
1. Pure conversational interface
2. Ask questions about code, get explanations
3. Context-aware (knows about your current project)

### Build Mode
1. Enter your project description
2. Select language/framework preferences
3. Click "Generate Project"
4. View plan and generated code
5. Preview or download your project

### File Regeneration
1. Generate a project first
2. Go to the "Regenerate" tab
3. Select the file you want to modify
4. Enter instructions (e.g., "Add error handling")
5. Click "Regenerate Selected File"

## 🐳 Docker Preview

### Requirements
- Docker Desktop installed and running
- Ports 8100-8200 available for preview containers

### Resource Limits
| Resource | Python Apps | Node.js Apps |
|----------|-------------|--------------|
| Memory | 512 MB | 1 GB |
| CPU | 0.5 cores | 0.5 cores |
| Timeout | 5-30 min | 5-30 min |

### How Preview Works
1. Code is written to a temporary directory
2. Docker container starts with mounted code
3. Dependencies installed (`pip install` or `npm install`)
4. App starts with exposed port
5. URL returned to user
6. Container auto-destroyed after TTL

## 📝 Notes

- **File Normalization**: Generated files are automatically normalized (e.g., `gitignore` → `.gitignore`)
- **Dependency Validation**: Prompts enforce that all imports have corresponding dependencies
- **Container Registry**: Running preview containers tracked in `.preview_registry.json`
- **JSON Parsing**: Robust parsing with retry logic and repair fallbacks
- **LangGraph**: Deterministic state-based routing (no vector DB, no retrievers)

## 🐛 Troubleshooting

### Configuration Error
Ensure your `.env` file:
- Exists in the project root
- Contains all required variables
- Has valid Azure OpenAI credentials

### Docker Not Running
```bash
# Check Docker status
docker info

# Start Docker (macOS)
open -a Docker
```

### Preview Not Loading
- Wait 3-5 minutes for Node.js apps (npm install takes time)
- Click "Check Status" to refresh
- View container logs for errors

### JSON Parse Errors
The app will:
1. Automatically retry with a clarified prompt
2. Attempt to repair common JSON issues
3. Show an error if all attempts fail

Try simplifying your request or regenerating.

### Content Filter Issues
Azure OpenAI has content filtering. If blocked:
- Rephrase your request
- Use simpler, more direct language

## 📦 Dependencies

```
streamlit
openai
pydantic
langgraph
docker
python-dotenv
```

## 📄 License

MIT
