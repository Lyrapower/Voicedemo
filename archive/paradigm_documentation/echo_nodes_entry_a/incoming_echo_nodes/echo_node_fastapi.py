"""Alias entrypoint (user scripts name echo_node_fastapi.py)."""
from echo_nodes_fastapi import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8500)
