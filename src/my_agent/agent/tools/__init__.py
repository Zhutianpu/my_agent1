"""内建工具注册处：新工具在这里登记一行即上线（契约铁律：别处不动）。"""

from .agent_delegate import AgentDelegateTool
from .agent_message import AgentMessageTool
from .bash_tool import RunCommandTool
from .current_time import CurrentTimeTool
from .edit_file import EditFileTool
from .ls import LsTool
from .memory_search import MemorySearchTool
from .read import ReadFileTool
from .search_files import SearchFilesTool
from .subagent_tool import SubagentTool
from .tool_manager import TOOLS
from .write import WriteFileTool

TOOLS.register(ReadFileTool)
TOOLS.register(WriteFileTool)
TOOLS.register(EditFileTool)
TOOLS.register(LsTool)
TOOLS.register(RunCommandTool)
TOOLS.register(SearchFilesTool)
TOOLS.register(CurrentTimeTool)
TOOLS.register(MemorySearchTool)
TOOLS.register(SubagentTool)  # 阶段 11：派发工具（子代理的白名单里没有它——铁律）
# P2：花名册协作两件套。AgentDelegateTool 注册实例——花名册现读现编进
# description（schema 是实例方法），改配置下个回合生效。
TOOLS.register(AgentDelegateTool())
TOOLS.register(AgentMessageTool)
