"""
AI Code Generator - Streamlit Application

A simple app that generates implementation plans and code from natural language descriptions.
"""

import streamlit as st

from src.config import ConfigError, get_config
from src.orchestrator import generate_project
from src.schemas import GenerationResult
from src.utils import make_zip_bytes, guess_language_from_filename, safe_project_name
from src.llm.azure_openai_client import JSONParseError


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
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state variables."""
    if "generation_result" not in st.session_state:
        st.session_state.generation_result = None
    if "last_query" not in st.session_state:
        st.session_state.last_query = ""
    if "error_message" not in st.session_state:
        st.session_state.error_message = None


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


def display_plan(result: GenerationResult):
    """Display the generated plan in a nice format."""
    plan = result.plan
    
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


def display_code(result: GenerationResult):
    """Display the generated code files with tabs."""
    code_bundle = result.code
    files = code_bundle.files
    
    st.subheader("💻 Generated Code")
    
    if code_bundle.notes:
        st.info(f"📝 **Notes:** {code_bundle.notes}")
    
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


def create_download_button(result: GenerationResult, user_query: str):
    """Create a download button for the generated code as a ZIP file."""
    files = result.code.files
    
    if not files:
        return
    
    # Create ZIP
    zip_bytes = make_zip_bytes(files)
    
    # Generate filename
    project_name = safe_project_name(user_query)
    filename = f"{project_name}.zip"
    
    st.download_button(
        label="📥 Download as ZIP",
        data=zip_bytes,
        file_name=filename,
        mime="application/zip",
        use_container_width=True,
    )


def main():
    """Main application entry point."""
    init_session_state()
    
    # Header
    st.markdown('<p class="main-header">🚀 AI Code Generator</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">Describe what you want to build → Get an implementation plan → Get complete code files</p>',
        unsafe_allow_html=True
    )
    
    # Validate configuration
    if not validate_config():
        return
    
    st.divider()
    
    # Input section
    st.subheader("📝 Describe Your Project")
    
    # User query input
    user_query = st.text_area(
        "What do you want to build?",
        placeholder="Example: Create a REST API in Python using FastAPI that manages a todo list with CRUD operations. Include SQLite database and Pydantic models.",
        height=120,
        key="user_query_input",
    )
    
    # Options in columns
    col1, col2 = st.columns(2)
    
    with col1:
        language_pref = st.selectbox(
            "Language Preference",
            options=["Auto", "Python", "JavaScript", "TypeScript", "Node.js", "Go", "Java", "C#", "Rust"],
            index=0,
            help="Select 'Auto' to let the AI choose the best language for your project",
        )
    
    with col2:
        framework_pref = st.text_input(
            "Framework Preference (optional)",
            placeholder="e.g., FastAPI, Express, Next.js, Spring Boot",
            help="Optionally specify a framework you want to use",
        )
    
    # Executable checkbox
    executable = st.checkbox(
        "Generate executable project (include run instructions)",
        value=True,
        help="Include setup and run instructions in the generated project",
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
        st.session_state.error_message = None
        
        with st.spinner("🔄 Generating your project... This may take a minute."):
            try:
                # Generate the project
                result = generate_project(
                    user_query=user_query.strip(),
                    language_pref=language_pref,
                    framework_pref=framework_pref.strip() if framework_pref else None,
                    executable=executable,
                )
                
                # Store in session state
                st.session_state.generation_result = result
                st.session_state.last_query = user_query.strip()
                
            except JSONParseError as e:
                st.session_state.error_message = f"Failed to parse AI response: {str(e)}"
                st.session_state.generation_result = None
                
            except Exception as e:
                st.session_state.error_message = f"An error occurred: {str(e)}"
                st.session_state.generation_result = None
    
    # Display error if any
    if st.session_state.error_message:
        st.error(st.session_state.error_message)
    
    # Display results if available
    if st.session_state.generation_result:
        result = st.session_state.generation_result
        
        st.success("✅ Project generated successfully!")
        
        # Download button at the top
        create_download_button(result, st.session_state.last_query)
        
        st.divider()
        
        # Display plan and code in tabs
        plan_tab, code_tab = st.tabs(["📋 Plan", "💻 Code"])
        
        with plan_tab:
            display_plan(result)
        
        with code_tab:
            display_code(result)


if __name__ == "__main__":
    main()

