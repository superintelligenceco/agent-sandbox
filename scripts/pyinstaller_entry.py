"""Entry point that PyInstaller freezes into the standalone `agent-sandbox` executable."""

from agent_sandbox.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
