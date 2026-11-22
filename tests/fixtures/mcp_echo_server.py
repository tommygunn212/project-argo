"""A tiny real MCP server over stdio, for proving the voice MCP bridge end to end."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("argo-test-echo")


@server.tool()
def echo(text: str) -> str:
    """Repeat the text back."""
    return f"echo: {text}"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    server.run()
