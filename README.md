# AI Code Generator (Plan → Code)

A Streamlit application that generates implementation plans and complete codebases from natural language descriptions using Azure OpenAI GPT.

## Features

- **Natural Language Input**: Describe what you want to build in plain English
- **Language Selection**: Choose from Python, JavaScript, TypeScript, Go, Java, C#, Rust, or let the AI decide
- **Framework Support**: Optionally specify a framework (FastAPI, Express, Next.js, etc.)
- **Two-Stage Generation**:
  1. **Plan**: AI analyzes your request and creates a structured implementation plan
  2. **Code**: AI generates complete, working code files based on the plan
- **Code Preview**: View all generated files with syntax highlighting
- **Download**: Export all files as a ZIP archive

## Requirements

- Python 3.9+
- Azure OpenAI API access

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

### 1. Plan Generation
When you submit a request, the AI first analyzes your requirements and creates a structured plan including:
- Recommended language and framework
- List of files to generate with purposes
- Required dependencies
- Steps to run the project

### 2. Code Generation
Using the plan, the AI generates complete code for each file:
- Production-ready code following best practices
- README with setup instructions
- Dependency files (requirements.txt, package.json, etc.)
- Proper .gitignore

### 3. Output
The generated project is displayed with:
- Interactive tabs for each file
- Syntax highlighting
- Line numbers
- One-click ZIP download

## Project Structure

```
.
├── app.py                          # Main Streamlit application
├── src/
│   ├── __init__.py
│   ├── config.py                   # Environment configuration
│   ├── schemas.py                  # Pydantic data models
│   ├── orchestrator.py             # Generation pipeline
│   ├── utils.py                    # Utility functions
│   └── llm/
│       ├── __init__.py
│       └── azure_openai_client.py  # Azure OpenAI client
│   └── prompts/
│       ├── plan_system.txt         # Prompt for planning
│       └── code_system.txt         # Prompt for code generation
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── .gitignore
└── README.md                       # This file
```

## Notes

- **No Code Execution**: This MVP only generates code—it does not execute or sandbox any generated code.
- **JSON Parsing**: The app includes robust JSON parsing with repair fallbacks to handle occasional model output issues.
- **Session State**: Your last generated project is preserved across Streamlit reruns.

## Troubleshooting

### Configuration Error
If you see a configuration error, ensure your `.env` file:
- Exists in the project root
- Contains all required variables
- Has valid Azure OpenAI credentials

### JSON Parse Errors
If the AI returns malformed JSON, the app will attempt automatic repair. If it still fails, try:
- Simplifying your request
- Being more specific about requirements
- Regenerating

### Content Filter Issues
Azure OpenAI has content filtering that may occasionally block certain prompts. If you encounter this:
- Try rephrasing your request
- Use simpler, more direct language

## License

MIT
