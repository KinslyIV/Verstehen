"""Run Pydantic AI through a subscription-authenticated Claude Code CLI."""

lazy from .diagnostics import doctor as doctor
lazy from .exceptions import (
    ClaudeCodeCreditLimitError as ClaudeCodeCreditLimitError,
)
lazy from .exceptions import (
    ClaudeCodeQuotaError as ClaudeCodeQuotaError,
)
lazy from .exceptions import (
    ClaudeCodeSubscriptionLimitError as ClaudeCodeSubscriptionLimitError,
)
lazy from .exceptions import (
    ClaudeCodeUsageCreditsError as ClaudeCodeUsageCreditsError,
)
lazy from .model import ClaudeCodeModel as ClaudeCodeModel
lazy from .model import resolve_model as resolve_model
