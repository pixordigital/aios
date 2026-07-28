"""Global tool registry. Maps tool name → code reference + metadata.

Built-in tools populate on import via _auto_register().
"""
import logging

logger = logging.getLogger(__name__)

TOOL_REGISTRY: dict[str, dict] = {}


def register(name: str, code_reference: str, description: str = "", builtin: bool = True):
    """Register a tool in the global registry."""
    TOOL_REGISTRY[name] = {
        "name": name,
        "code_reference": code_reference,
        "description": description,
        "is_builtin": builtin,
        "status": "active",
    }


def _auto_register():
    """Populate registry with built-in tools."""
    builtins = [
        ("calculator", "aios.tools.calculator.CalculatorTool", "Perform arithmetic calculations"),
        ("web_search", "aios.tools.web_search.WebSearchTool", "Search the web for current information"),
        ("send_email", "aios.tools.send_email.SendEmailTool", "Send an email message"),
        ("read_file", "aios.tools.read_file.ReadFileTool", "Read file content from storage"),
        ("current_datetime", "aios.tools.current_datetime.CurrentDateTimeTool", "Get current date and time"),
        ("http_get", "aios.tools.http_get.HttpGetTool", "Make HTTP GET requests"),
    ]
    for name, ref, desc in builtins:
        register(name, ref, desc)
    logger.info("Registered %d built-in tools", len(builtins))


_auto_register()
