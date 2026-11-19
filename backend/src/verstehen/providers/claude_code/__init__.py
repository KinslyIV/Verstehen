"""Run Pydantic AI through a subscription-authenticated Claude Code CLI."""

from .diagnostics import doctor as doctor
from .exceptions import (
    ClaudeCodeCreditLimitError as ClaudeCodeCreditLimitError,
)
from .exceptions import (
    ClaudeCodeQuotaError as ClaudeCodeQuotaError,
)
from .exceptions import (
    ClaudeCodeSubscriptionLimitError as ClaudeCodeSubscriptionLimitError,
)
from .exceptions import (
    ClaudeCodeUsageCreditsError as ClaudeCodeUsageCreditsError,
)
from .model import ClaudeCodeModel as ClaudeCodeModel
from .model import resolve_model as resolve_model
