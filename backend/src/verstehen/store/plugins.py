import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PluginsStateError(Exception):
    """`plugins-state.json` cannot be read; the file is never overwritten."""


class PluginsState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: dict[str, bool] = Field(default_factory=dict)


class PluginsStore:
    """Keep each plugin's enable choice in `<data dir>/plugins-state.json`; a missing file is empty."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "plugins-state.json"

    def read(self) -> PluginsState:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return PluginsState()
        except OSError as error:
            raise PluginsStateError(
                f"Cannot read plugins-state.json: {error}"
            ) from error
        try:
            return PluginsState.model_validate_json(text)
        except ValidationError as error:
            raise PluginsStateError(
                f"Invalid or unsupported plugins-state.json: {error.errors()[0]['msg']}"
            ) from error

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        state = self.read()
        state.enabled[plugin_id] = enabled
        self.write(state)

    def write(self, state: PluginsState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".plugins-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(state.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
