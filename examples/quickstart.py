"""Create a sandbox, break it, and roll it back with the Python SDK.

Run the server first (``docker compose up -d``), then::

    export AGENT_SANDBOX_URL=http://localhost:8080
    export AGENT_SANDBOX_API_KEY=...
    python examples/quickstart.py
"""

from agent_sandbox.client import SandboxClient

with SandboxClient() as client, client.create(image="python:3.12-slim", timeout_seconds=600) as sandbox:
    print("created", sandbox)

    sandbox.write_file("app.py", "print('hello from', __import__('platform').python_version())\n")
    print("run 1:", sandbox.exec("python3 app.py").stdout.strip())

    good = sandbox.snapshot("working")
    print("snapshot", good.id, f"({good.size_bytes} bytes)")

    broken = sandbox.exec("rm app.py && python3 app.py")
    print("after rm: exit", broken.exit_code, "|", broken.stderr.strip())

    sandbox.rollback(good)
    print("after rollback:", sandbox.exec("python3 app.py").stdout.strip())

    for event in sandbox.exec_stream("for i in 1 2 3; do echo tick $i; sleep 0.2; done"):
        print("stream:", event)
