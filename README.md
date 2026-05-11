# HoudiniMCP – Connect Houdini to Claude via Model Context Protocol

> **macOS fork** of [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp).
> The upstream project assumes Windows + the legacy OpenGL ROP, which crashes
> Houdini instantly on macOS. This fork is macOS-only — use upstream for
> Windows. See [What Changed and Why](#what-changed-and-why) for the full list.

**HoudiniMCP** allows you to control **SideFX Houdini** from **Claude** using the **Model Context Protocol (MCP)**. It consists of:

1. A **Houdini plugin** (Python package) that listens on a local port (default `localhost:9876`) and handles commands (creating and modifying nodes, executing code, rendering views, etc.).
2. An **MCP bridge script** you run via **uv** that communicates via **stdin/stdout** with Claude and **TCP** with Houdini.

Below are the complete instructions for setting up Houdini, uv, and Claude Desktop.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Houdini MCP Plugin Installation](#houdini-mcp-plugin-installation)
   1. [Folder Layout](#folder-layout)
   2. [Shelf Tool](#shelf-tool)
   3. [Packages Integration (Optional)](#packages-integration-optional)
3. [Installing the `mcp` Python Package with uv](#installing-the-mcp-python-package-with-uv)
4. [Telling Claude Desktop to Use the Bridge](#telling-claude-desktop-to-use-the-bridge)
5. [Using Another IDE / Harness](#using-another-ide--harness)
6. [Render Engines](#render-engines)
7. [What Changed and Why](#what-changed-and-why)
8. [Acknowledgement](#acknowledgement)

---

## Requirements

- **SideFX Houdini** — tested on 21.0.631. Houdini 20+ on macOS uses PySide6 and Vulkan/Metal; this fork supports that.
- **uv** — <https://docs.astral.sh/uv/>
- **Claude Desktop** (latest)

---

## 1. Houdini MCP Plugin Installation

### 1.1 Folder Layout

Create a folder in your Houdini scripts directory:

```
~/houdini21.0/scripts/python/houdinimcp/
```

If that folder doesn't exist yet, just create it under your home directory — Houdini will pick it up.

**Not sure where your home directory is?** Launch Houdini → **Help** menu → type "shell" in the search; it'll show you where the shell option lives. Open the shell and type:

```
$HOME
```

That prints your home path. Create the `houdini21.0/scripts/python/houdinimcp/` chain of folders there — any folder along the path that doesn't already exist, make it.

Inside that `houdinimcp/` folder, place:

- **`__init__.py`** – handles plugin initialization (start/stop server)
- **`server.py`** – defines the `HoudiniMCPServer` (listening on port `9876`)
- **`houdini_mcp_server.py`** – optional bridging script (some prefer a separate location)
- **`pyproject.toml`**

### 1.2 Shelf Tool

Create a **Shelf Tool** to toggle the server in Houdini:

1. **Right-click** a shelf → **"New Shelf..."** — name it "MCP".
2. **Right-click** again → **"New Tool..."** — Name: `Toggle MCP Server`, Label: `MCP`.
3. Under **Script**, paste exactly (no leading indentation):

```python
import hou
import houdinimcp

if hasattr(hou.session, "houdinimcp_server") and hou.session.houdinimcp_server:
    houdinimcp.stop_server()
    hou.ui.displayMessage("Houdini MCP Server stopped")
else:
    houdinimcp.start_server()
    hou.ui.displayMessage("Houdini MCP Server started on localhost:9876")
```

### 1.3 Packages Integration (Optional)

If you want Houdini to auto-load the plugin at startup, create `houdinimcp.json` in whichever packages directory you normally use. If you don't have one, drop it into the install's bundled packages folder, e.g.:

```
/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/21.0/Resources/packages
```

(swap `21.0.631` for your installed version).

```json
{
  "path": "$HOME/houdini21.0/scripts/python/houdinimcp",
  "load_package_once": true,
  "version": "0.1",
  "env": [
    { "PYTHONPATH": "$PYTHONPATH;$HOME/houdini21.0/scripts/python" }
  ]
}
```

---

## 2. Installing the `mcp` Python Package with uv

```bash
# 1) Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) Verify uv is on your PATH
which uv
# expected: /Users/<you>/.local/bin/uv

# 3) Inside the plugin directory, install deps
cd ~/houdini21.0/scripts/python/houdinimcp
uv add "mcp[cli]"

# 4) Sanity check
uv run python -c "import mcp.server.fastmcp; print('mcp ok')"
```

If `uv add` errors with **"No `pyproject.toml` found in current directory or any parent directory"**, initialise the project first then add:

```bash
uv init
uv add "mcp[cli]"
```

If `python` isn't recognised on your machine (common on macOS — system only ships `python3`), substitute `python3` in the sanity-check command:

```bash
uv run python3 -c "import mcp.server.fastmcp; print('mcp ok')"
```

---

## 3. Telling Claude Desktop to Use the Bridge

Claude Desktop's config lives at `~/Library/Application Support/Claude/claude_desktop_config.json`. The block you need to register is:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "/Users/<YourUserName>/.local/bin/uv",
      "args": [
        "run",
        "--directory",
        "/Users/<YourUserName>/houdini21.0/scripts/python/houdinimcp",
        "python",
        "/Users/<YourUserName>/houdini21.0/scripts/python/houdinimcp/houdini_mcp_server.py"
      ]
    }
  }
}
```

Swap `<YourUserName>` for your actual macOS username, and make sure the path under `--directory` is the **same path** you created during the [Folder Layout](#11-folder-layout) step (the literal path, not `$HOME`).

> ⚠️ **Do not just paste this block over the top of your existing config.** That file already contains your Claude settings — if you wipe it, Claude will overwrite it with defaults on next launch and you'll lose them. You need to **merge** the `"mcpServers"` key into the existing JSON.

Easiest way to do that safely: ask Claude itself to do it for you. Open Claude Desktop, ask:

> "Open my Claude Desktop config and add this MCP server entry without breaking anything else: \<paste the block above\>"

If you'd rather edit by hand: open the file, find the top-level object, and add the `"mcpServers"` key alongside the existing keys (commas matter).

**Why the full path to `uv`?** macOS GUI apps don't inherit your shell `PATH`. A bare `"command": "uv"` may silently fail to launch. Find your path with `which uv` and use that.

After editing the config you must **fully quit** Claude Desktop (Cmd+Q) and reopen — closing the window isn't enough.

**Claude code may still give a disconnected error at the start.** It's best to restart Claude after adding the MCP server and restart the MCP server. Use the shelf tool to toggle the server.

---

## 4. Using Another IDE / Harness

Most MCP-aware tools (Cursor, Zed, Cline, Continue, etc.) accept the same `mcpServers` JSON block shown above. The exact location of the config file differs per tool.

The easiest path is to ask the model running in that IDE/harness to set it up for you — paste the JSON block from section 3 and say *"register this MCP server in this IDE's config."* It'll find the right file and merge the entry.

**Tested with Claude, Hermes and Cline.**

---

## 6. Render Engines

| Engine    | Status     | Notes |
|-----------|------------|-------|
| `vulkan`  | ✅ Tested  | **Default.** Aliased to the `flipbook` ROP — viewport-quality, fast. Runs through MoltenVK on Metal. |
| `karma`   | ✅ Tested  | Works on macOS. |
| `mantra`  | ❌ Removed | Node creates but produces no output. |
| `opengl`  | ❌ Removed | Crashes Houdini instantly. Was the upstream default. The `flipbook` ROP is the functional replacement. |

---

## 7. What Changed and Why

This fork's deltas vs upstream `capoomgit/houdini-mcp`:

### `HoudiniMCPRender.py`
- **OpenGL ROP support removed.** The legacy `opengl` node type is still registered in Houdini 21 but creating one on macOS causes an instant crash (no GL context — macOS runs Houdini on Vulkan via MoltenVK on Metal).
- **New `vulkan` engine.** Houdini does not ship a standalone "Vulkan ROP," so the default render option `vulkan` is rerouted to the `flipbook` ROP, replacing the legacy opengl ROP and uses whatever the active viewport renderer is.
- **`SUPPORTED_RENDER_ENGINES` whitelist** added so unsupported values raise a clear `ValueError` instead of falling through to the (now-removed) opengl branch.
- **`C:/temp/` defaults replaced with `tempfile.gettempdir()`** so the default render path resolves correctly on any OS. It may default to `/private/tmp/`.

### `houdini_mcp_server.py` (the bridge)
- **`FastMCP(description=...)` → `FastMCP(instructions=...)`.** Newer `mcp[cli]` releases renamed the kwarg; the old name now raises `TypeError` at startup.
- **Render-tool defaults** changed: `render_engine="opengl"` → `"vulkan"`, `render_path="C:/temp/"` → `tempfile.gettempdir()`.

### `server.py` (the TCP listener inside Houdini)
- **PySide6 import with PySide2 fallback.** Houdini 20+ on macOS ships PySide6 only; the upstream `from PySide2 import …` fails with `ModuleNotFoundError`.
- **Render handler defaults** changed to `render_engine="vulkan"`.

### `pyproject.toml`
- Bumped `mcp[cli]>=1.4.1` → `>=1.27.1` (matches the kwarg rename above).

### OPUS removed
- The OPUS / RapidAPI integration has been gutted entirely. OPUS was abandoned by its provider and the API is no longer reachable. All `opus_*` MCP tools, the import/unzip pipeline, the RapidAPI helpers, `urls.env`, `python-dotenv`, `langchain`, and `requests` dependencies have been removed.

### Other
- README rewritten for macOS.

---

## Acknowledgement

HoudiniMCP was originally built by [capoomgit](https://github.com/capoomgit/houdini-mcp) following [blender-mcp](https://github.com/ahujasid/blender-mcp). Thanks to both for the foundation.
