"""
AI Code Generator - Streamlit Application

A smart app that generates implementation plans and code from natural language descriptions.
Now with chat, auto-routing, and per-file regeneration capabilities.
"""

import streamlit as st

from src.config import ConfigError, get_config
from src.orchestrator import run_auto, run_chat, run_build, run_regen_file
from src.schemas import GenerationResult, Plan, CodeBundle, ChatTurn
from src.utils import make_zip_bytes, guess_language_from_filename, safe_project_name
from src.llm.azure_openai_client import JSONParseError
from src.sandbox.preview import (
    start_preview, 
    stop_preview, 
    get_preview_status, 
    get_container_logs,
    is_previewable,
    detect_framework,
)


# Page configuration
st.set_page_config(
    page_title="AI Code Generator",
    page_icon="🚀",
    layout="wide",
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E88E5;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .file-tab {
        font-family: 'Fira Code', 'Consolas', monospace;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        background-color: #f0f2f6;
        border-radius: 8px 8px 0 0;
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border-radius: 8px;
        border-left: 4px solid #28a745;
    }
    .plan-section {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    .chat-message {
        padding: 0.75rem 1rem;
        border-radius: 12px;
        margin-bottom: 0.5rem;
        max-width: 80%;
    }
    .user-message {
        background-color: #1E88E5;
        color: white;
        margin-left: auto;
    }
    .assistant-message {
        background-color: #f0f2f6;
        color: #333;
    }
    .chat-container {
        max-height: 400px;
        overflow-y: auto;
        padding: 1rem;
        border: 1px solid #ddd;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables for memory."""
    # Chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # Build artifacts
    if "last_plan" not in st.session_state:
        st.session_state.last_plan = None
    if "last_codebundle" not in st.session_state:
        st.session_state.last_codebundle = None
    if "last_build_query" not in st.session_state:
        st.session_state.last_build_query = ""
    if "last_prefs" not in st.session_state:
        st.session_state.last_prefs = None
    
    # Intent tracking
    if "last_intent" not in st.session_state:
        st.session_state.last_intent = None
    
    # Error tracking
    if "errors" not in st.session_state:
        st.session_state.errors = []
    
    # Legacy compatibility
    if "generation_result" not in st.session_state:
        st.session_state.generation_result = None
    if "error_message" not in st.session_state:
        st.session_state.error_message = None
    
    # Preview state
    if "preview_result" not in st.session_state:
        st.session_state.preview_result = None
    if "session_id" not in st.session_state:
        import uuid
        st.session_state.session_id = str(uuid.uuid4())
    if "show_preview_logs" not in st.session_state:
        st.session_state.show_preview_logs = False


def get_chat_history_as_turns():
    """Convert session chat history to ChatTurn objects."""
    turns = []
    for item in st.session_state.chat_history:
        if isinstance(item, dict):
            turns.append(ChatTurn(role=item.get("role", "user"), content=item.get("content", "")))
        elif isinstance(item, ChatTurn):
            turns.append(item)
    return turns


def update_chat_history(new_history):
    """Update session chat history from ChatTurn list."""
    result = []
    for turn in new_history:
        if isinstance(turn, ChatTurn):
            result.append({"role": turn.role, "content": turn.content})
        elif isinstance(turn, dict):
            result.append(turn)
    st.session_state.chat_history = result


def validate_config() -> bool:
    """Validate configuration and show error if missing."""
    try:
        get_config()
        return True
    except ConfigError as e:
        st.error(f"⚠️ Configuration Error\n\n{str(e)}")
        st.info(
            "Please create a `.env` file in the project root with the required Azure OpenAI credentials. "
            "See `.env.example` for reference."
        )
        return False


def display_chat_history():
    """Display the chat history in a nice format."""
    if not st.session_state.chat_history:
        st.info("💬 No conversation yet. Start chatting!")
        return
    
    for msg in st.session_state.chat_history:
        role = msg.get("role", "user") if isinstance(msg, dict) else msg.role
        content = msg.get("content", "") if isinstance(msg, dict) else msg.content
        
        if role == "user":
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-end; margin-bottom: 0.5rem;">
                <div class="chat-message user-message">
                    <strong>You:</strong> {content}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-start; margin-bottom: 0.5rem;">
                <div class="chat-message assistant-message">
                    <strong>Assistant:</strong> {content}
                </div>
            </div>
            """, unsafe_allow_html=True)


def display_plan(plan: Plan):
    """Display the generated plan in a nice format."""
    st.subheader("📋 Implementation Plan")
    
    # Summary
    st.markdown(f"**Summary:** {plan.summary}")
    
    # Tech stack in columns
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Language", plan.language)
    with col2:
        st.metric("Framework", plan.framework or "None")
    with col3:
        st.metric("Files", len(plan.files))
    
    # Files to generate
    with st.expander("📁 Files to Generate", expanded=True):
        for f in plan.files:
            st.markdown(f"- `{f.path}` - {f.purpose}")
    
    # Dependencies
    if plan.dependencies:
        with st.expander("📦 Dependencies"):
            for dep in plan.dependencies:
                st.markdown(f"- `{dep}`")
    
    # Run steps
    if plan.steps:
        with st.expander("🚀 Run Steps"):
            for i, step in enumerate(plan.steps, 1):
                st.markdown(f"{i}. `{step}`")
    
    # Raw JSON view
    with st.expander("🔍 View Raw Plan JSON"):
        st.json(plan.model_dump())


def display_code(codebundle: CodeBundle):
    """Display the generated code files with tabs."""
    files = codebundle.files
    
    st.subheader("💻 Generated Code")
    
    if codebundle.notes:
        st.info(f"📝 **Notes:** {codebundle.notes}")
    
    # Sort files: README first, then by path
    sorted_files = sorted(
        files.items(),
        key=lambda x: (0 if x[0].lower() == "readme.md" else 1, x[0])
    )
    
    # Create tabs for each file
    if sorted_files:
        file_names = [path for path, _ in sorted_files]
        tabs = st.tabs(file_names)
        
        for tab, (path, content) in zip(tabs, sorted_files):
            with tab:
                language = guess_language_from_filename(path)
                st.code(content, language=language, line_numbers=True)
    else:
        st.warning("No files were generated.")


def create_download_button(codebundle: CodeBundle, query: str):
    """Create a download button for the generated code as a ZIP file."""
    files = codebundle.files
    
    if not files:
        return
    
    # Create ZIP
    zip_bytes = make_zip_bytes(files)
    
    # Generate filename
    project_name = safe_project_name(query)
    filename = f"{project_name}.zip"
    
    st.download_button(
        label="📥 Download as ZIP",
        data=zip_bytes,
        file_name=filename,
        mime="application/zip",
        use_container_width=True,
    )


def display_regen_section(plan: Plan, codebundle: CodeBundle):
    """Display the file regeneration section."""
    st.subheader("🔄 Regenerate File")
    st.caption("Select a file and provide instructions to regenerate it.")
    
    file_paths = list(codebundle.files.keys())
    
    selected_file = st.selectbox(
        "Select file to regenerate",
        options=file_paths,
        key="regen_file_select"
    )
    
    regen_instructions = st.text_area(
        "Regeneration instructions",
        placeholder="Example: Add error handling and input validation. Use type hints.",
        height=100,
        key="regen_instructions"
    )
    
    if st.button("🔄 Regenerate Selected File", type="primary", use_container_width=True):
        if not regen_instructions.strip():
            st.warning("Please provide regeneration instructions.")
            return
        
        with st.spinner(f"Regenerating {selected_file}..."):
            try:
                result = run_regen_file(
                    file_path=selected_file,
                    instructions=regen_instructions.strip(),
                    existing_plan=plan,
                    existing_codebundle=codebundle,
                    chat_history=get_chat_history_as_turns(),
                )
                
                if result.get("errors"):
                    for err in result["errors"]:
                        st.error(err)
                else:
                    # Update session state
                    new_codebundle = result.get("codebundle")
                    if new_codebundle:
                        st.session_state.last_codebundle = new_codebundle
                        if result.get("chat_history"):
                            update_chat_history(result["chat_history"])
                        st.success(f"✅ Successfully regenerated `{selected_file}`!")
                        st.rerun()
                    else:
                        st.error("Regeneration did not return updated code.")
                        
            except Exception as e:
                st.error(f"Regeneration failed: {str(e)}")


def display_errors():
    """Display any errors from session state."""
    if st.session_state.errors:
        for error in st.session_state.errors:
            st.error(error)


def display_preview_section(plan: Plan, codebundle: CodeBundle):
    """Display the preview hosting section with start/stop and URL."""
    st.subheader("🌐 Preview App")
    
    # Check if preview is supported
    can_preview = is_previewable(codebundle, plan)
    framework = detect_framework(codebundle, plan)
    
    if not can_preview:
        st.info(
            f"⚠️ Preview not available for this project. "
            f"Preview hosting requires a web framework (FastAPI, Flask, Express, Next.js, etc.).\n\n"
            f"**Tip:** Download the code and run it locally for CLI applications."
        )
        return
    
    # Show framework info
    st.caption(f"🔧 Detected framework: **{framework}** ({plan.language if plan else 'Unknown'})")
    
    # Check current preview status
    session_id = st.session_state.get("session_id", "default")
    current_status = get_preview_status(session_id)
    
    # Handle different statuses
    if current_status:
        if current_status.status == "running":
            display_running_preview(current_status)
        elif current_status.status == "starting":
            display_starting_preview(current_status)
        elif current_status.status in ("stopped", "expired", "error"):
            # Show error/stopped message then show controls to start again
            if current_status.status == "error":
                st.error(f"❌ Preview failed: {current_status.message or 'Unknown error'}")
                if current_status.logs:
                    with st.expander("View error logs"):
                        st.code(current_status.logs, language="text")
            elif current_status.status == "expired":
                st.warning("⏰ Previous preview has expired.")
            display_preview_controls(codebundle, plan, framework, session_id)
        else:
            display_preview_controls(codebundle, plan, framework, session_id)
    else:
        display_preview_controls(codebundle, plan, framework, session_id)


def display_starting_preview(preview_result):
    """Display a preview that is still starting (installing dependencies)."""
    st.warning("🔄 **Preview is starting...** Please wait while dependencies are being installed.")
    
    # Progress indicator
    st.markdown("""
    <style>
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .starting-indicator {
        animation: pulse 2s infinite;
        padding: 10px;
        background: linear-gradient(90deg, #1e3a5f, #2d5a87);
        border-radius: 8px;
        margin: 10px 0;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Show message
    st.info(preview_result.message or "Installing dependencies... This may take a few minutes for Node.js projects.")
    
    # Show time remaining
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("⏱️ Time Remaining", preview_result.time_remaining or "N/A")
    with col2:
        st.metric("🔌 Port", preview_result.port or "N/A")
    with col3:
        st.metric("📦 Framework", preview_result.framework or "Unknown")
    
    st.divider()
    
    # Auto-refresh notice
    st.caption("🔄 Click 'Check Status' to see if your app is ready, or wait for auto-refresh.")
    
    # Control buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Check Status", type="primary", use_container_width=True, key="check_status"):
            st.rerun()
    
    with col2:
        if st.button("📜 View Logs", use_container_width=True, key="view_starting_logs"):
            st.session_state.show_preview_logs = True
            st.rerun()
    
    with col3:
        if st.button("🛑 Cancel", use_container_width=True, key="cancel_preview"):
            with st.spinner("Stopping preview..."):
                result = stop_preview(preview_result.container_id)
                st.session_state.preview_result = None
                st.rerun()
    
    # Always show logs when starting
    st.markdown("### 📜 Container Logs (Live)")
    logs = preview_result.logs or get_container_logs(preview_result.container_id, tail=30)
    if logs:
        st.code(logs, language="text")
    else:
        st.caption("No logs yet...")
    
    # Auto-refresh hint
    st.markdown("---")
    st.info("💡 **Tip:** Keep clicking 'Check Status' every few seconds until your app is ready. For Node.js apps, dependency installation typically takes 2-5 minutes.")


def display_running_preview(preview_result):
    """Display a running preview with URL and controls."""
    st.success("✅ Preview is running!")
    
    # URL display with copy button
    st.markdown("### 🔗 Access Your App")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.code(preview_result.url, language=None)
    with col2:
        st.link_button("🔗 Open", preview_result.url, use_container_width=True)
    
    # Status info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("⏱️ Time Remaining", preview_result.time_remaining)
    with col2:
        st.metric("🔌 Port", preview_result.port)
    with col3:
        st.metric("📦 Framework", preview_result.framework or "Unknown")
    
    st.divider()
    
    # Control buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Refresh Status", use_container_width=True, key="refresh_preview"):
            st.rerun()
    
    with col2:
        if st.button("📜 View Logs", use_container_width=True, key="view_logs"):
            st.session_state.show_preview_logs = True
            st.rerun()
    
    with col3:
        if st.button("🛑 Stop Preview", type="primary", use_container_width=True, key="stop_preview"):
            with st.spinner("Stopping preview..."):
                result = stop_preview(preview_result.container_id)
                st.session_state.preview_result = None
                if result.status == "stopped":
                    st.success("Preview stopped successfully!")
                else:
                    st.warning(result.message or "Preview may have already stopped.")
                st.rerun()
    
    # Show logs if requested
    if st.session_state.get("show_preview_logs", False):
        st.markdown("### 📜 Container Logs")
        logs = get_container_logs(preview_result.container_id, tail=50)
        st.code(logs, language="text")
        if st.button("Hide Logs", key="hide_logs"):
            st.session_state.show_preview_logs = False
            st.rerun()
    
    # Important notice
    st.info(
        "💡 **Note:** The preview will automatically stop after the time expires. "
        "Your app is running in an isolated Docker container."
    )


def display_preview_controls(codebundle: CodeBundle, plan: Plan, framework: str, session_id: str):
    """Display controls to start a new preview."""
    
    st.markdown("""
    **🚀 Start a live preview of your web application!**
    
    Your app will run in a Docker container with an exposed port. 
    You can interact with it in your browser for up to 15 minutes.
    """)
    
    # TTL selection
    ttl_options = {
        "5 minutes": 5,
        "10 minutes": 10,
        "15 minutes (default)": 15,
        "30 minutes": 30,
    }
    
    selected_ttl = st.selectbox(
        "Preview duration",
        options=list(ttl_options.keys()),
        index=2,  # Default to 15 minutes
        key="preview_ttl_select"
    )
    ttl_minutes = ttl_options[selected_ttl]
    
    # Start button
    if st.button("🚀 Start Preview", type="primary", use_container_width=True, key="start_preview"):
        with st.spinner("🐳 Starting preview container... This may take a moment."):
            result = start_preview(
                codebundle=codebundle,
                plan=plan,
                session_id=session_id,
                ttl_minutes=ttl_minutes,
            )
            
            st.session_state.preview_result = result.to_dict()
            
            if result.status == "running":
                st.success(f"✅ Preview started! Access at: {result.url}")
                st.rerun()
            elif result.status == "already_running":
                st.warning(result.message)
                st.rerun()
            else:
                st.error(f"❌ {result.message}")
    
    # Info about what happens
    with st.expander("ℹ️ How Preview Hosting Works"):
        st.markdown("""
        1. **Container Created**: Your code runs in an isolated Docker container
        2. **Port Exposed**: The container exposes a port accessible via localhost
        3. **URL Returned**: You get a URL like `http://localhost:8100`
        4. **Interact**: Open the URL in your browser to use your app
        5. **Auto-Cleanup**: Container is destroyed after the time expires
        
        **Supported Frameworks:**
        - Python: FastAPI, Flask, Django, Streamlit, Gradio
        - Node.js: Express, Next.js, React, Vue, Angular
        
        **Requirements:**
        - Docker must be installed and running
        - The app must expose an HTTP server
        """)


# =============================================================================
# MODE HANDLERS
# =============================================================================

def handle_auto_mode():
    """Handle Auto mode - routes based on intent detection."""
    st.subheader("🤖 Auto Mode")
    st.caption("Type anything - I'll automatically detect if you want to chat, build, or modify files.")
    
    # Show build preferences (collapsed by default)
    with st.expander("⚙️ Build Preferences (for project generation)"):
        col1, col2 = st.columns(2)
        with col1:
            language_pref = st.selectbox(
                "Language Preference",
                options=["Auto", "Python", "JavaScript", "TypeScript", "Node.js", "Go", "Java", "C#", "Rust"],
                index=0,
                key="auto_language_pref"
            )
        with col2:
            framework_pref = st.text_input(
                "Framework (optional)",
                placeholder="e.g., FastAPI, Express",
                key="auto_framework_pref"
            )
        executable = st.checkbox("Generate executable project", value=True, key="auto_executable")
    
    # User input
    user_input = st.text_area(
        "What would you like to do?",
        placeholder="Examples:\n• Hello, how are you?\n• Create a Python Flask REST API for managing tasks\n• Update the README to include more details",
        height=100,
        key="auto_input"
    )
    
    if st.button("✨ Send", type="primary", use_container_width=True, disabled=not user_input.strip()):
        st.session_state.errors = []
        
        with st.spinner("Processing..."):
            try:
                result = run_auto(
                    user_input=user_input.strip(),
                    language_pref=language_pref,
                    framework_pref=framework_pref.strip() if framework_pref else None,
                    executable=executable,
                    chat_history=get_chat_history_as_turns(),
                    existing_plan=st.session_state.last_plan,
                    existing_codebundle=st.session_state.last_codebundle,
                )
                
                # Update session state
                st.session_state.last_intent = result.get("intent")
                
                if result.get("chat_history"):
                    update_chat_history(result["chat_history"])
                
                if result.get("plan"):
                    st.session_state.last_plan = result["plan"]
                    st.session_state.last_build_query = user_input.strip()
                
                if result.get("codebundle"):
                    st.session_state.last_codebundle = result["codebundle"]
                
                if result.get("errors"):
                    st.session_state.errors = result["errors"]
                
                st.rerun()
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
    
    st.divider()
    
    # Show intent detection result
    if st.session_state.last_intent:
        intent_colors = {"chat": "🗣️", "build": "🔨", "regen_file": "🔄"}
        st.caption(f"Last detected intent: {intent_colors.get(st.session_state.last_intent, '❓')} **{st.session_state.last_intent}**")
    
    # Display errors
    display_errors()
    
    # Display chat history
    if st.session_state.chat_history:
        st.subheader("💬 Conversation")
        display_chat_history()
    
    # Display build results if available
    if st.session_state.last_plan and st.session_state.last_codebundle:
        st.divider()
        create_download_button(st.session_state.last_codebundle, st.session_state.last_build_query)
        
        plan_tab, code_tab, preview_tab, regen_tab = st.tabs([
            "📋 Plan", "💻 Code", "🌐 Preview", "🔄 Regenerate"
        ])
        
        with plan_tab:
            display_plan(st.session_state.last_plan)
        
        with code_tab:
            display_code(st.session_state.last_codebundle)
        
        with preview_tab:
            display_preview_section(st.session_state.last_plan, st.session_state.last_codebundle)
        
        with regen_tab:
            display_regen_section(st.session_state.last_plan, st.session_state.last_codebundle)


def handle_chat_mode():
    """Handle Chat mode - pure conversation."""
    st.subheader("💬 Chat Mode")
    st.caption("Have a conversation with the AI assistant.")
    
    # Display chat history
    st.markdown("### Conversation")
    display_chat_history()
    
    # Chat input at bottom
    user_input = st.text_input(
        "Your message",
        placeholder="Type your message here...",
        key="chat_input"
    )
    
    col1, col2 = st.columns([4, 1])
    with col1:
        send_clicked = st.button("📤 Send", type="primary", use_container_width=True)
    with col2:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()
    
    if send_clicked and user_input.strip():
        with st.spinner("Thinking..."):
            try:
                result = run_chat(
                    user_input=user_input.strip(),
                    chat_history=get_chat_history_as_turns(),
                    existing_plan=st.session_state.last_plan,
                    existing_codebundle=st.session_state.last_codebundle,
                )
                
                if result.get("chat_history"):
                    update_chat_history(result["chat_history"])
                
                if result.get("errors"):
                    for err in result["errors"]:
                        st.error(err)
                
                st.rerun()
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
    
    # Show context if project exists
    if st.session_state.last_plan:
        with st.expander("📁 Current Project Context"):
            st.write(f"**Project:** {st.session_state.last_plan.summary}")
            st.write(f"**Language:** {st.session_state.last_plan.language}")
            if st.session_state.last_codebundle:
                st.write(f"**Files:** {', '.join(st.session_state.last_codebundle.files.keys())}")


def handle_build_mode():
    """Handle Build mode - project generation."""
    st.subheader("🔨 Build Mode")
    st.caption("Generate complete projects from natural language descriptions.")
    
    # User query input
    user_query = st.text_area(
        "What do you want to build?",
        placeholder="Example: Create a REST API in Python using FastAPI that manages a todo list with CRUD operations. Include SQLite database and Pydantic models.",
        height=120,
        key="build_query_input",
    )
    
    # Options in columns
    col1, col2 = st.columns(2)
    
    with col1:
        language_pref = st.selectbox(
            "Language Preference",
            options=["Auto", "Python", "JavaScript", "TypeScript", "Node.js", "Go", "Java", "C#", "Rust"],
            index=0,
            help="Select 'Auto' to let the AI choose the best language for your project",
            key="build_language_pref"
        )
    
    with col2:
        framework_pref = st.text_input(
            "Framework Preference (optional)",
            placeholder="e.g., FastAPI, Express, Next.js, Spring Boot",
            help="Optionally specify a framework you want to use",
            key="build_framework_pref"
        )
    
    # Executable checkbox
    executable = st.checkbox(
        "Generate executable project (include run instructions)",
        value=True,
        help="Include setup and run instructions in the generated project",
        key="build_executable"
    )
    
    # Generate button
    generate_clicked = st.button(
        "✨ Generate Project",
        type="primary",
        use_container_width=True,
        disabled=not user_query.strip(),
    )
    
    st.divider()
    
    # Handle generation
    if generate_clicked and user_query.strip():
        st.session_state.errors = []
        
        with st.spinner("🔄 Generating your project... This may take a minute."):
            try:
                result = run_build(
                    user_input=user_query.strip(),
                    language_pref=language_pref,
                    framework_pref=framework_pref.strip() if framework_pref else None,
                    executable=executable,
                    chat_history=get_chat_history_as_turns(),
                )
                
                # Update session state
                if result.get("plan"):
                    st.session_state.last_plan = result["plan"]
                    st.session_state.last_build_query = user_query.strip()
                    st.session_state.last_prefs = {
                        "language_pref": language_pref,
                        "framework_pref": framework_pref,
                        "executable": executable
                    }
                
                if result.get("codebundle"):
                    st.session_state.last_codebundle = result["codebundle"]
                
                if result.get("chat_history"):
                    update_chat_history(result["chat_history"])
                
                if result.get("errors"):
                    st.session_state.errors = result["errors"]
                    for err in result["errors"]:
                        st.error(err)
                else:
                    st.success("✅ Project generated successfully!")
                
                st.rerun()
                
            except JSONParseError as e:
                st.error(f"Failed to parse AI response: {str(e)}")
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
    
    # Display errors
    display_errors()
    
    # Display results if available
    if st.session_state.last_plan and st.session_state.last_codebundle:
        st.success("✅ Project generated successfully!")
        
        # Download button at the top
        create_download_button(st.session_state.last_codebundle, st.session_state.last_build_query)
        
        st.divider()
        
        # Display plan, code, preview, and regen in tabs
        plan_tab, code_tab, preview_tab, regen_tab = st.tabs([
            "📋 Plan", "💻 Code", "🌐 Preview", "🔄 Regenerate File"
        ])
        
        with plan_tab:
            display_plan(st.session_state.last_plan)
        
        with code_tab:
            display_code(st.session_state.last_codebundle)
        
        with preview_tab:
            display_preview_section(st.session_state.last_plan, st.session_state.last_codebundle)
        
        with regen_tab:
            display_regen_section(st.session_state.last_plan, st.session_state.last_codebundle)


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application entry point."""
    init_session_state()
    
    # Header
    st.markdown('<p class="main-header">🚀 AI Code Generator</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">Chat, build projects, and regenerate files with AI assistance</p>',
        unsafe_allow_html=True
    )
    
    # Validate configuration
    if not validate_config():
        return
    
    # Sidebar mode selection
    with st.sidebar:
        st.header("Mode")
        mode = st.radio(
            "Select mode",
            options=["🤖 Auto", "💬 Chat", "🔨 Build"],
            index=0,
            help="Auto: Intelligent routing based on your input\nChat: Pure conversation\nBuild: Project generation"
        )
        
        st.divider()
        
        # Session info
        st.header("Session Info")
        st.write(f"💬 Chat messages: {len(st.session_state.chat_history)}")
        if st.session_state.last_plan:
            st.write(f"📋 Current project: {st.session_state.last_plan.language}")
        if st.session_state.last_codebundle:
            st.write(f"📁 Files: {len(st.session_state.last_codebundle.files)}")
        
        st.divider()
        
        # Clear session button
        if st.button("🗑️ Clear Session", use_container_width=True):
            for key in ["chat_history", "last_plan", "last_codebundle", "last_build_query", 
                       "last_prefs", "last_intent", "errors", "generation_result", "error_message"]:
                if key in st.session_state:
                    st.session_state[key] = [] if key in ["chat_history", "errors"] else None
            st.rerun()
    
    st.divider()
    
    # Route to appropriate mode handler
    if "Auto" in mode:
        handle_auto_mode()
    elif "Chat" in mode:
        handle_chat_mode()
    elif "Build" in mode:
        handle_build_mode()


if __name__ == "__main__":
    main()
