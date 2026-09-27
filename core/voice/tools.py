"""The capability tools the realtime model can call, grouped by domain.

Each tool is a thin, documented door onto ``core.realtime_tools``, where the
bodies live so they can be unit-tested without a LiveKit session. The
docstrings are not commentary: the SDK sends them to the model as the tool
descriptions, so they are worded for her, not for us.

Every call is threaded, because the capabilities do blocking IO, WMI and COM,
and every result is handed back as JSON. ``ArgoRealtimeAgent`` inherits all
of these through ``CapabilityTools``. Grep ``@function_tool`` before adding
one - it probably exists.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from livekit.agents import function_tool

from core import realtime_tools as capabilities


async def _call(capability: Callable[..., dict], *args: Any) -> str:
    """Run a blocking capability off the event loop and hand the model JSON."""
    result = await asyncio.to_thread(capability, *args)
    return json.dumps(result, default=str)


class MachineTools:
    """This PC: hardware, health, volume and performance profile."""

    @function_tool()
    async def get_pc_specs(self) -> str:
        """This PC's hardware: motherboard, BIOS, CPU, memory and graphics card."""
        return await _call(capabilities.pc_specs)

    @function_tool()
    async def get_drive_space(self) -> str:
        """Free and used space for every drive on this PC."""
        return await _call(capabilities.drive_space)

    @function_tool()
    async def get_system_status(self) -> str:
        """Live machine health: memory use, temperatures, overall status."""
        return await _call(capabilities.system_status)

    @function_tool()
    async def run_self_diagnostics(self) -> str:
        """Run ARGO's own diagnostics to find what is broken inside it."""
        return await _call(capabilities.diagnostics)

    @function_tool()
    async def set_volume(self, percent: int) -> str:
        """Set the system volume, 0 to 100."""
        return await _call(capabilities.volume_set, percent)

    @function_tool()
    async def get_volume(self) -> str:
        """Current system volume and mute state."""
        return await _call(capabilities.volume_status)

    @function_tool()
    async def set_pc_profile(self, mode: str) -> str:
        """Switch the PC between "gaming" and "editing" profiles - power
        plan, display refresh rate, and any configured background apps to
        close. mode must be "gaming" or "editing"."""
        return await _call(capabilities.pc_profile_set, mode)

    @function_tool()
    async def get_pc_profile_status(self) -> str:
        """Current power plan, display refresh rate, and which PC profile -
        gaming or editing - was applied last."""
        return await _call(capabilities.pc_profile_status)


class FileTools:
    """Reading, finding and writing files. Deletion is quarantine, never removal."""

    @function_tool()
    async def list_argo_files(self, subfolder: str = "") -> str:
        """List ARGO's own files and folders. Pass a subfolder like "core", or "" for the root."""
        return await _call(capabilities.list_folder, subfolder)

    @function_tool()
    async def list_folder(self, path: str = "") -> str:
        """List any folder ARGO has permission to read.

        Absolute paths must be inside a folder Tommy granted in config.json.
        If it is refused, tell him it needs adding to filesystem.allowed_folders.
        """
        return await _call(capabilities.list_folder, path)

    @function_tool()
    async def read_text_file(self, path: str) -> str:
        """Read a text file inside a folder ARGO has permission to read."""
        return await _call(capabilities.read_text_file, path)

    @function_tool()
    async def find_files(self, query: str) -> str:
        """Search the folders ARGO can read for files matching a name or keyword."""
        return await _call(capabilities.find_files, query)

    @function_tool()
    async def search_drives(self, query: str, want: str = "any") -> str:
        """Find a file or FOLDER by name across every drive.

        want is any, file or folder. Most things Tommy names - "my vzbot
        build", "the davinci assets" - are folders, so search folders too.
        """
        return await _call(capabilities.find_files, query, want)

    @function_tool()
    async def get_file_access(self) -> str:
        """Which drives can be read and written, and what is off limits."""
        return await _call(capabilities.file_access_report)

    @function_tool()
    async def write_file(self, path: str, content: str, overwrite: bool = False) -> str:
        """Write a text file. Refuses to replace an existing file unless
        overwrite is true - say so before replacing something."""
        return await _call(capabilities.write_text_file, path, content, overwrite)

    @function_tool()
    async def append_to_file(self, path: str, content: str) -> str:
        """Add text to the end of a file, creating it if needed."""
        return await _call(capabilities.append_text_file, path, content)

    @function_tool()
    async def make_folder(self, path: str) -> str:
        """Create a folder."""
        return await _call(capabilities.create_folder, path)

    @function_tool()
    async def move_file(self, source: str, destination: str, overwrite: bool = False) -> str:
        """Move or rename a file or folder."""
        return await _call(capabilities.move_item, source, destination, overwrite)

    @function_tool()
    async def copy_file(self, source: str, destination: str, overwrite: bool = False) -> str:
        """Copy a file or folder."""
        return await _call(capabilities.copy_item, source, destination, overwrite)

    @function_tool()
    async def remove_file(self, path: str) -> str:
        """Move a file or folder to quarantine. This does NOT delete it -
        say so: it goes to a quarantine folder Tommy empties himself."""
        return await _call(capabilities.remove_item, path)


class MusicTools:
    """The local music library and player."""

    @function_tool()
    async def play_music(self, query: str = "", kind: str = "keyword") -> str:
        """Play music. kind is song, artist, genre, keyword or random."""
        return await _call(capabilities.music_play, query, kind)

    @function_tool()
    async def play_music_from_era(self, era: str, genre: str = "", artist: str = "") -> str:
        """Play music from a period: "the 80s", "1975", "1990s", "1975 to 1980".

        Optionally narrow by genre or artist.
        """
        return await _call(capabilities.music_play_era, era, genre, artist)

    @function_tool()
    async def stop_music(self) -> str:
        """Stop music playback."""
        return await _call(capabilities.music_stop)

    @function_tool()
    async def next_track(self) -> str:
        """Skip to the next track."""
        return await _call(capabilities.music_next)

    @function_tool()
    async def get_music_status(self) -> str:
        """What is playing right now, if anything."""
        return await _call(capabilities.music_status)

    @function_tool()
    async def check_music_library(self) -> str:
        """Whether the music index still matches what is on disk.

        Use this when music will not play, or before claiming the library
        has something. An index can outlive the files it points at.
        """
        return await _call(capabilities.music_library_status)


class AppTools:
    """Launching, switching and typing into desktop applications."""

    @function_tool()
    async def list_launchable_apps(self) -> str:
        """What applications ARGO can open, including what is pinned to the taskbar.

        Use when asked what you can launch, or when an app name was not found.
        """
        return await _call(capabilities.apps_launchable)

    @function_tool()
    async def open_app(self, name: str) -> str:
        """Launch an application by name, e.g. "notepad", "chrome", "spotify"."""
        return await _call(capabilities.app_open, name)

    @function_tool()
    async def close_app(self, name: str) -> str:
        """Close an application by name."""
        return await _call(capabilities.app_close, name)

    @function_tool()
    async def focus_app(self, name: str) -> str:
        """Bring an application to the front."""
        return await _call(capabilities.app_focus, name)

    @function_tool()
    async def list_running_apps(self) -> str:
        """What applications are running, and which one is in front."""
        return await _call(capabilities.apps_running)

    @function_tool()
    async def write_in_app(self, name: str, text: str) -> str:
        """Type text into an open app window. Only Notepad and Word accept text.

        Opens the app first if it is not running. For any other app this
        returns not_writable - say so rather than claiming it was written.
        """
        return await _call(capabilities.app_write, name, text)

    @function_tool()
    async def list_writable_apps(self) -> str:
        """Which apps can be typed into, as opposed to merely opened."""
        return await _call(capabilities.writable_apps)


class VideoTools:
    """Movies and TV from the local library."""

    @function_tool()
    async def play_movie(self, title: str) -> str:
        """Put a movie on screen by name, full screen.

        Reports whether it STAYED playing, not just that a player launched.
        """
        return await _call(capabilities.video_play, title, "movie")

    @function_tool()
    async def play_episode(self, title: str) -> str:
        """Play a TV episode by name or by the show it belongs to."""
        return await _call(capabilities.video_play, title, "episode")

    @function_tool()
    async def find_something_to_watch(self, query: str, kind: str = "movie") -> str:
        """Search the movie and TV library. kind is movie, episode or series."""
        return await _call(capabilities.video_search, query, kind)

    @function_tool()
    async def stop_video(self) -> str:
        """Close whatever movie or episode is on screen."""
        return await _call(capabilities.video_stop)

    @function_tool()
    async def get_video_status(self) -> str:
        """What is on screen now, and how many movies and episodes exist."""
        return await _call(capabilities.video_status)


class HomeTools:
    """Home Assistant devices and the GE SmartHQ air conditioners."""

    @function_tool()
    async def control_smart_home(self, command: str) -> str:
        """Control a Home Assistant device: lights, switches, climate, locks, scenes.

        Pass the request close to how Tommy said it - "turn on Jesse's
        light", "dim the living room light to 30 percent", "make Jesse's
        light blue", "is the living room light on", "turn off the living
        room light". Also answers "what devices do I have" / "list my
        lights". If Home Assistant is not configured, say so plainly rather
        than guessing at device names.
        """
        return await _call(capabilities.smart_home_command, command)

    @function_tool()
    async def list_air_conditioners(self) -> str:
        """List the GE SmartHQ air conditioners ARGO can see, with their state."""
        return await _call(capabilities.ac_list)

    @function_tool()
    async def get_ac_status(self, name: str) -> str:
        """Current state of one air conditioner: on/off, room temp, target, mode."""
        return await _call(capabilities.ac_status, name)

    @function_tool()
    async def control_ac(self, name: str, power: str = "", temperature_f: int = 0,
                          mode: str = "", fan: str = "") -> str:
        """Turn an air conditioner on/off, or set its temperature, mode or fan speed.

        power is "on" or "off" - leave it "" if power should not change.
        temperature_f is 60-86 - leave it 0 if it should not change.
        mode and fan are whatever was said ("cool", "auto", "low", "high") -
        leave "" if they should not change. Only pass what Tommy actually
        asked to change, and report back what the unit says its state is
        now, not just that the command was sent.
        """
        return await _call(capabilities.ac_control, name, power, temperature_f, mode, fan)


class WritingTools:
    """Drafts on disk. Nothing here sends anything."""

    @function_tool()
    async def save_draft(self, kind: str, title: str, body: str, recipient: str = "") -> str:
        """Save a draft to disk. kind is email, document, blog or note.

        This only writes a file. It never sends anything.
        """
        return await _call(capabilities.draft_write, kind, title, body, recipient)

    @function_tool()
    async def list_drafts(self, category: str = "", limit: int = 10) -> str:
        """List saved drafts, newest first."""
        return await _call(capabilities.drafts_list, category, limit)

    @function_tool()
    async def read_draft(self, name: str) -> str:
        """Read back a saved draft by name."""
        return await _call(capabilities.draft_read, name)

    @function_tool()
    async def check_email_sending(self) -> str:
        """Whether email sending is set up. ARGO cannot send email by voice."""
        return await _call(capabilities.email_status)


class KnowledgeTools:
    """Tommy's own written record, via AnythingLLM."""

    @function_tool()
    async def search_knowledge_base(self, query: str) -> str:
        """Look up Tommy's own knowledge base for biographical or written-record answers.

        This is his AnythingLLM library - his about-me profile, wiki notes,
        blog mirrors, and book manuscript - not ordinary conversation
        history (use recall() for that). Reach for this when he asks
        something about his own life, writing, or history that isn't
        already in your instructions or memory: "what did I write about
        the Gunn Kraft build", "what's in my writing guide", "what's my
        maker background". Not for small talk or anything about right now.
        """
        return await _call(capabilities.rag_search, query)


class CapabilityTools(MachineTools, FileTools, MusicTools, AppTools, VideoTools,
                      HomeTools, WritingTools, KnowledgeTools):
    """Every capability tool, for the agent to inherit."""
