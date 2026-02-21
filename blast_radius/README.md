# Blast Radius MCP Server

Change impact analysis for Python repositories via the Model Context Protocol (MCP).

This server exposes 5 MCP tools:

- `get_ast_dependencies` (Tool 1): structural AST dependencies
- `trace_data_shape` (Tool 2): data lineage across handlers and models
- `find_semantic_neighbors` (Tool 3): semantic neighbors (embeddings or BM25 fallback)
- `get_historical_coupling` (Tool 4): temporal coupling from git history
- `get_covering_tests` (Tool 5): likely impacted tests

## Prerequisites

- Python 3.11+
- `git` (needed for historical coupling and repo fingerprinting)
- Optional (for embedding-backed semantic search):
	- OpenAI API key
	- Pinecone API key + index/host

## Setup (local development)

From the `blast_radius/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Quick check:

```bash
which blast-radius-mcp
```

## Environment variables

The server reads environment variables with the `BLAST_RADIUS_` prefix (and also loads `.env` when present):

- `BLAST_RADIUS_REPO_ROOT` (default: `.`)
- `BLAST_RADIUS_CACHE_DB_PATH` (default: `~/.blast_radius/cache.db`)
- `BLAST_RADIUS_SCHEMA_VERSION` (default: `v1`)
- `BLAST_RADIUS_LOG_LEVEL` (default: `INFO`)
- `BLAST_RADIUS_OPENAI_API_KEY` (optional)
- `BLAST_RADIUS_OPENAI_EMBEDDING_MODEL` (default: `text-embedding-3-small`)
- `BLAST_RADIUS_PINECONE_API_KEY` (optional)
- `BLAST_RADIUS_PINECONE_INDEX` (default: `blast-radius`)
- `BLAST_RADIUS_PINECONE_HOST` (optional)

Example `.env`:

```bash
BLAST_RADIUS_REPO_ROOT=.
BLAST_RADIUS_CACHE_DB_PATH=.cache/blast-radius/cache.db
BLAST_RADIUS_LOG_LEVEL=INFO

# Optional semantic embedding config
BLAST_RADIUS_OPENAI_API_KEY=
BLAST_RADIUS_PINECONE_API_KEY=
BLAST_RADIUS_PINECONE_INDEX=blast-radius
BLAST_RADIUS_PINECONE_HOST=
```

## Run the MCP server

```bash
blast-radius-mcp
```

This runs the MCP server over stdio (foreground process), which is what MCP clients (VS Code/OpenCode) expect for local servers.

## Initialize Tool 3 semantic index (embedding path)

For a new target repository, you can warm the semantic vector index once before demos:

```bash
python scripts/init_tool3_semantic_index.py \
	--repo-root /absolute/path/to/target_repo
```

Required embedding settings:

- `BLAST_RADIUS_OPENAI_API_KEY`
- `BLAST_RADIUS_PINECONE_API_KEY`
- `BLAST_RADIUS_PINECONE_INDEX`
- `BLAST_RADIUS_PINECONE_HOST`

Behavior:

- Runs Tool 3 in `mode=embedding`.
- Prints retrieval mode, backend, indexed chunk stats, diagnostics.
- Exits `0` only when retrieval mode is `embedding_primary`.

## Connect in VS Code

VS Code MCP config is stored in `.vscode/mcp.json` for workspace-scoped servers.

1. Open Command Palette → `MCP: Open Workspace Folder Configuration`.
2. Add this configuration to `.vscode/mcp.json`:

```json
{
	"servers": {
		"blastRadius": {
			"type": "stdio",
			"command": "${workspaceFolder}/blast_radius/.venv/bin/blast-radius-mcp",
			"envFile": "${workspaceFolder}/blast_radius/.env",
			"env": {
				"BLAST_RADIUS_REPO_ROOT": "${workspaceFolder}",
				"BLAST_RADIUS_CACHE_DB_PATH": "${workspaceFolder}/.cache/blast-radius/cache.db",
				"BLAST_RADIUS_LOG_LEVEL": "INFO"
			}
		}
	}
}
```

3. Run `MCP: List Servers` and start `blastRadius`.
4. In Chat, enable tools from the `blastRadius` server in the tool picker.

Notes:

- On first run, VS Code will ask you to trust the server.
- If tools don’t refresh, run `MCP: Reset Cached Tools`.

## Connect in OpenCode

OpenCode MCP servers are configured under `mcp` in `opencode.json` (project root) or `~/.config/opencode/opencode.json` (global).

Example `opencode.json` at workspace root:

```json
{
	"$schema": "https://opencode.ai/config.json",
	"mcp": {
		"blast_radius": {
			"type": "local",
			"command": ["./blast_radius/.venv/bin/blast-radius-mcp"],
			"enabled": true,
			"timeout": 15000,
			"environment": {
				"BLAST_RADIUS_REPO_ROOT": ".",
				"BLAST_RADIUS_CACHE_DB_PATH": ".cache/blast-radius/cache.db",
				"BLAST_RADIUS_LOG_LEVEL": "INFO",
				"BLAST_RADIUS_OPENAI_API_KEY": "{env:BLAST_RADIUS_OPENAI_API_KEY}",
				"BLAST_RADIUS_PINECONE_API_KEY": "{env:BLAST_RADIUS_PINECONE_API_KEY}",
				"BLAST_RADIUS_PINECONE_HOST": "{env:BLAST_RADIUS_PINECONE_HOST}"
			}
		}
	}
}
```

Then verify and debug:

```bash
opencode mcp list
opencode mcp debug blast_radius
```

When prompting, explicitly mention using this MCP (example):

```text
Analyze blast radius for renaming field user_id to account_id in payment routes. Use blast_radius.
```

## Run tests

```bash
pytest -q tests
```

Latest verified result: 186 passing tests.
