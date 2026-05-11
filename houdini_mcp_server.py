#!/usr/bin/env python
"""
houdini_mcp_server.py

This is the "bridge" or "driver" script that Claude will run via `uv run`.
It uses the MCP library (fastmcp) to communicate with Claude over stdio,
and relays each command to the local Houdini plugin on port 9876.
"""
import sys
import os
import site
import tempfile


import json
import socket
import logging
from dataclasses import dataclass
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio

@dataclass
class HoudiniConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self) -> bool:
        """Connect to the Houdini plugin (which is listening on self.host:self.port)."""
        if self.sock is not None:
            return True  # Already connected
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Houdini at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Houdini: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        """Close socket if open."""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Houdini: {str(e)}")
            self.sock = None

    def send_command(self, cmd_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a JSON command to Houdini's server and wait for the JSON response.
        Returns the parsed Python dict (e.g. {"status": "success", "result": {...}})
        """
        if not self.connect():
            # Instead of raising, return an error dict consistent with API errors
            error_msg = "Could not connect to Houdini on port 9876."
            logger.error(error_msg)
            # Return structure similar to API failures
            return {"status": "error", "message": error_msg, "origin": "mcp_server_connection"}
            # raise ConnectionError("Could not connect to Houdini on port 9876.") # Original way

        command = {"type": cmd_type, "params": params or {}}
        data_out = json.dumps(command).encode("utf-8")

        try:
            # Send the command
            self.sock.sendall(data_out)
            logger.info(f"Sent command to Houdini: {command}")

            # Read response. We'll accumulate chunks until we can parse a full JSON.
            chunks = []
            self.sock.settimeout(10.0) # Use TIMEOUT? Or keep specific timeout for Houdini comms?
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                 # Check for timeout
                if asyncio.get_event_loop().time() - start_time > 10.0: # Use same timeout value
                     raise socket.timeout("Timeout waiting for Houdini response")
                     
                # Non-blocking read if possible, or use select/poll?
                # Sticking with blocking recv with timeout for now
                chunk = self.sock.recv(8192)
                if not chunk:
                    # Connection closed gracefully by Houdini?
                    if buffer: # If we have partial data, it's an error
                         raise ConnectionAbortedError("Connection closed by Houdini with incomplete data.")
                    else: # No data received and socket closed -> Houdini might have crashed?
                         raise ConnectionAbortedError("Connection closed by Houdini before sending data.")
                         
                buffer += chunk
                # Try to decode the accumulated buffer
                try:
                    decoded_string = buffer.decode("utf-8")
                    # Attempt to load JSON from the decoded string
                    parsed = json.loads(decoded_string)
                    # If successful, we have a complete JSON object
                    logger.info(f"Received response from Houdini: {parsed}")
                    return parsed
                except json.JSONDecodeError:
                    # Not a complete JSON object yet, continue receiving
                    continue
                except UnicodeDecodeError:
                    # Data received is not valid UTF-8
                     logger.error("Received non-UTF-8 data from Houdini")
                     raise ValueError("Received non-UTF-8 data from Houdini")

            # Should not be reached if loop exits via return or exception
            # raise Exception("No (or incomplete) data from Houdini; EOF reached without valid JSON.")

        except socket.timeout: # Explicitly catch socket timeout
            error_msg = "Timeout receiving data from Houdini."
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command_timeout"}
        except Exception as e:
            error_msg = f"Error during Houdini communication for command '{cmd_type}': {str(e)}"
            logger.error(error_msg)
            # Invalidate socket so we reconnect next time
            self.disconnect()
            # Return error dict consistent with API failures
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command"}
            # raise # Re-raise original exception? Or return dict? Returning dict.


# A global Houdini connection object
_houdini_connection: HoudiniConnection = None

def get_houdini_connection() -> HoudiniConnection:
    """Get or create a persistent HoudiniConnection object."""
    global _houdini_connection
    if _houdini_connection is None:
        logger.info("Creating new HoudiniConnection.")
        _houdini_connection = HoudiniConnection(host="localhost", port=9876)

    # Always try to connect, returns True if already connected or successful now
    if not _houdini_connection.connect():
         # Connection failed, reset _houdini_connection to allow retry next time?
         _houdini_connection = None
         raise ConnectionError("Could not connect to Houdini on localhost:9876. Is the plugin running?")
         
    return _houdini_connection


# Now define the MCP server that Claude will talk to over stdio
mcp = FastMCP(
    "HoudiniMCP",
    instructions="A bridging server that connects Claude to Houdini via MCP stdio + TCP, with OPUS API integration."
)

@asynccontextmanager
async def server_lifespan(app: FastMCP):
    """Startup/shutdown logic. Called automatically by fastmcp."""
    logger.info("Houdini MCP server starting up (stdio).")
    # Attempt to connect right away? Or lazily on first call? Lazy seems safer.
    # try:
    #     get_houdini_connection()
    #     logger.info("Successfully connected to Houdini on startup.")
    # except Exception as e:
    #     logger.warning(f"Could not connect to Houdini on startup: {e}")
    #     logger.warning("Make sure Houdini is running with the plugin on port 9876.")
    yield {} # Context is empty for now
    logger.info("Houdini MCP server shutting down.")
    global _houdini_connection
    if _houdini_connection is not None:
        _houdini_connection.disconnect()
        _houdini_connection = None
    logger.info("Connection to Houdini closed.")

mcp.lifespan = server_lifespan


# -------------------------------------------------------------------
# Original Houdini Tools (Get/Create Node, Execute Code)
# -------------------------------------------------------------------
@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """
    Ask Houdini for scene info. Returns JSON as a string.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("get_scene_info")
        # response should look like {"status": "success", "result": {...}} or {"status": "error", ...}
        if response.get("status") == "error":
            # Include origin if available
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2) # Return empty dict if no result
    except ConnectionError as e:
         return f"Connection Error getting scene info: {str(e)}"
    except Exception as e:
        # Catch-all for unexpected errors in this function
        logger.error(f"Unexpected error in get_scene_info tool: {str(e)}", exc_info=True)
        return f"Server Error retrieving scene info: {str(e)}"

@mcp.tool()
def create_node(ctx: Context, node_type: str, parent_path: str = "/obj", name: str = None) -> str:
    """
    Create a new node in Houdini.
    """
    try:
        conn = get_houdini_connection()
        params = { "node_type": node_type, "parent_path": parent_path }
        if name: params["name"] = name
        response = conn.send_command("create_node", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        # Assuming result contains node info like {'name': ..., 'path': ..., 'type': ...}
        return f"Node created: {json.dumps(response.get('result', {}), indent=2)}"
    except ConnectionError as e:
         return f"Connection Error creating node: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in create_node tool: {str(e)}", exc_info=True)
        return f"Server Error creating node: {str(e)}"

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Houdini's environment.
    Returns status and any stdout/stderr generated by the code.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("execute_code", {"code": code})

        # Handle Houdini-side errors first (could be connection error or execution error)
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        # Handle success case (response should have status=success and a result dict)
        result = response.get("result", {}) # Default to empty dict
        if result.get("executed"): # Check if executed flag is True
            stdout = result.get("stdout", "").strip()
            stderr = result.get("stderr", "").strip()

            output_message = "Code executed successfully."
            if stdout:
                output_message += f"\\n--- Stdout ---\\n{stdout}"
            if stderr:
                output_message += f"\\n--- Stderr ---\\n{stderr}"
            return output_message
        else:
            # Unexpected success response format or executed flag missing/false
            logger.warning(f"execute_houdini_code received success status but unexpected result format: {response}")
            return f"Execution status unclear from Houdini response: {json.dumps(response)}"

    except ConnectionError as e:
         return f"Connection Error executing code: {str(e)}"
    except Exception as e:
        # Errors during communication or parsing in this script
        logger.error(f"Unexpected error in execute_houdini_code tool: {str(e)}", exc_info=True)
        return f"Server Error executing code: {str(e)}"

# -------------------------------------------------------------------
# NEW rendering Tools
# -------------------------------------------------------------------
@mcp.tool()
def render_single_view(ctx: Context,
                       orthographic: bool = False,
                       rotation: List[float] = [0, 90, 0],
                       render_path: str = tempfile.gettempdir(),
                       render_engine: str = "vulkan",
                       karma_engine: str = "cpu") -> str:
    """
    Render a single view inside Houdini and return the rendered image path.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_single_view", {
            "orthographic": orthographic,
            "rotation": rotation,
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_single_view failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_quad_views(ctx: Context,
                      render_path: str = tempfile.gettempdir(),
                      render_engine: str = "vulkan",
                      karma_engine: str = "cpu") -> str:
    """
    Render 4 canonical views from Houdini and return the image paths.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_quad_view", {
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output returned.")
    except Exception as e:
        logger.error(f"render_quad_views failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_specific_camera(ctx: Context,
                           camera_path: str,
                           render_path: str = tempfile.gettempdir(),
                           render_engine: str = "vulkan",
                           karma_engine: str = "cpu") -> str:
    """
    Render from a specific camera path in the Houdini scene.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_specific_camera", {
            "camera_path": camera_path,
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_specific_camera failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"



# ... (rest of existing code, main function etc) ...


def main():
    """Run the MCP server on stdio."""
    mcp.run()

if __name__ == "__main__":
    main()
