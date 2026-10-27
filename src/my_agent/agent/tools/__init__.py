"""内建工具注册处：新工具在这里登记一行即上线（契约铁律：别处不动）。"""

from .bash_tool import RunCommandTool
from .ls import LsTool
from .read import ReadFileTool
from .search_files import SearchFilesTool
from .tool_manager import TOOLS
from .write import WriteFileTool

TOOLS.register(ReadFileTool)
TOOLS.register(WriteFileTool)
TOOLS.register(LsTool)
TOOLS.register(RunCommandTool)
TOOLS.register(SearchFilesTool)
