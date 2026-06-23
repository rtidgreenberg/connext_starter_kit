"""Startup string configuration — save/load user selections."""

import shlex
from dataclasses import dataclass
from typing import Optional


@dataclass
class ViewConfig:
    """A persistable view configuration."""

    domain_id: int = 0
    topic_name: str = ""
    field_path: str = ""
    mode: str = "text"  # "text" or "plot"
    history_seconds: int = 30

    def to_startup_string(self) -> str:
        """Serialize to a CLI invocation string."""
        parts = ["./run_rti_view.sh"]
        parts.extend(["-d", str(self.domain_id)])
        if self.topic_name:
            parts.extend(["-t", shlex.quote(self.topic_name)])
        if self.field_path:
            parts.extend(["-f", shlex.quote(self.field_path)])
        parts.extend(["-m", self.mode])
        if self.mode == "plot":
            parts.extend(["--history", str(self.history_seconds)])
        return " ".join(parts)

    @classmethod
    def from_startup_string(cls, s: str) -> "ViewConfig":
        """Parse a startup string back into a ViewConfig."""
        import argparse

        parser = argparse.ArgumentParser(prog="rti_view", add_help=False)
        parser.add_argument("-d", "--domain", type=int, default=0)
        parser.add_argument("-t", "--topic", type=str, default="")
        parser.add_argument("-f", "--field", type=str, default="")
        parser.add_argument("-m", "--mode", choices=["text", "plot"], default="text")
        parser.add_argument("--history", type=int, default=30)

        tokens = shlex.split(s)
        # Skip the program name (./rti_view.sh, rti_view, etc.)
        args = parser.parse_args(tokens[1:] if tokens else [])
        return cls(
            domain_id=args.domain,
            topic_name=args.topic,
            field_path=args.field,
            mode=args.mode,
            history_seconds=args.history,
        )


def save_config(config: ViewConfig, filepath: str) -> None:
    """Save a startup string to a file."""
    with open(filepath, "w") as f:
        f.write(config.to_startup_string() + "\n")


def load_config(filepath: str) -> Optional[ViewConfig]:
    """Load a startup string from a file."""
    try:
        with open(filepath, "r") as f:
            line = f.readline().strip()
            if line:
                return ViewConfig.from_startup_string(line)
    except (FileNotFoundError, OSError):
        pass
    return None
