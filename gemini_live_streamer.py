"""
Gemini Live Desktop Companion (Project Astra-style Live Screen & Voice Streamer)
Powered by Google Gemini Multimodal Live API (bidiGenerateContent).

Features:
- Continuous 1 FPS Desktop Screen Video Streaming (sub-50ms Win32 ctypes capture)
- Real-Time Full-Duplex Voice Conversation (16kHz Mic Input, 24kHz Speaker Output)
- Autonomous Live Computer Tool Execution (mouse clicks, typing, window focus, app launch)
"""

import sys
import os
import io
import time
import asyncio
import threading
import traceback
import subprocess
import webbrowser
import urllib.parse
from typing import Optional

# Ensure Windows terminal doesn't crash on Unicode emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import dotenv
from PIL import Image
import pyaudio

dotenv.load_dotenv()

# Verify API key
if not os.getenv("GEMINI_API_KEY"):
    raise RuntimeError("GEMINI_API_KEY not found in environment or .env file.")

from google import genai
from google.genai import types

# Import our native Win32 screen and window managers
try:
    from .screen_vision import _screenshot_win32_ctypes, execute_action_plan, type_text, click_mouse, press_key, scroll_screen, move_mouse
    from .window_manager import focus_window, get_active_window
    from .gemini_floating_widget import GeminiFloatingWidget
    from .camera_vision import overlay_camera_pip, _camera_mgr
except (ImportError, ValueError):
    from screen_vision import _screenshot_win32_ctypes, execute_action_plan, type_text, click_mouse, press_key, scroll_screen, move_mouse
    from window_manager import focus_window, get_active_window
    from gemini_floating_widget import GeminiFloatingWidget
    from camera_vision import overlay_camera_pip, _camera_mgr

# Live Audio Specs
AUDIO_IN_RATE = 16000
AUDIO_IN_CHUNK = 1024
AUDIO_OUT_RATE = 24000

# Live Video Specs
SCREEN_FPS = 1.0  # 1 frame per second for optimal latency and bandwidth
FRAME_WIDTH = 640
FRAME_HEIGHT = 360

# Available Live Native Audio Models
LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"


def _launch_browser_url(url: str):
    """Opens URL directly in Google Chrome if installed, falling back to default browser."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, url], shell=False)
                return
            except Exception:
                pass
    webbrowser.open(url)


def _open_application(app_name: str) -> str:
    """Launches or switches to a Windows desktop application like a human user using the taskbar search pad and verifies window presence."""
    app_clean = app_name.strip()
    app_lower = app_clean.lower()

    try:
        # 1. If user asked to play music or YouTube via open_application, route directly to play_music!
        if any(w in app_lower for w in ("music", "song", "play", "youtube")):
            clean = app_name
            for word in ["open chrome and play", "open chrome to play", "open chrome and", "play some", "play", "open"]:
                clean = clean.replace(word, "").replace(word.title(), "").strip()
            return _play_music(clean)

        # 2. Check if the window is already running and visible on screen
        hwnd, title = _find_window_hwnd(app_clean)
        if hwnd:
            focus_window(app_clean)
            return f"Verified: Found running '{title}' and brought it directly to the front of your screen."

        # 3. Human Frontend Search Method: Click the taskbar Search pill, type, press Enter
        import pyautogui
        pyautogui.FAILSAFE = False
        w, h = pyautogui.size()
        search_x = int(w * 0.375)  # roughly 720 on 1920x1080 centered taskbar
        search_y = h - 25

        print(f"[HUMAN SEARCH] Clicking search bar at ({search_x}, {search_y}) for '{app_clean}'...")
        with attach_desktop():
            pyautogui.click(search_x, search_y)
            time.sleep(0.7)
            pyautogui.write(app_clean, interval=0.04)
            time.sleep(0.9)
            pyautogui.press('enter')

        # Wait for app window to launch
        time.sleep(2.0)
        hwnd, title = _find_window_hwnd(app_clean)
        if hwnd:
            focus_window(app_clean)
            return f"Verified: Successfully launched '{title}' via Windows Search and brought it to your screen."

        # 4. Fallback: Direct executable alias launch
        print(f"[FALLBACK LAUNCH] Human search did not yield window. Launching executable for '{app_clean}'...")
        alias_path = os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WindowsApps\{app_lower}.exe")
        if os.path.exists(alias_path):
            subprocess.Popen([alias_path], shell=False)
        elif "notepad" in app_lower:
            notepad_alias = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\notepad.exe")
            if os.path.exists(notepad_alias):
                subprocess.Popen([notepad_alias], shell=False)
            else:
                subprocess.Popen(["notepad.exe"], shell=False)
        elif any(c in app_lower for c in ("calc", "calculator")):
            subprocess.Popen(["cmd.exe", "/c", "start", "calc:"], shell=False)
        elif any(b in app_lower for b in ("chrome", "browser", "google")):
            _launch_browser_url("https://www.google.com")
        elif any(cd in app_lower for cd in ("code", "vscode", "vs code")):
            subprocess.Popen(["cmd.exe", "/c", "code"], shell=False)
        elif "spotify" in app_lower:
            subprocess.Popen(["cmd.exe", "/c", "start", "spotify:"], shell=False)
        elif "whatsapp" in app_lower:
            subprocess.Popen(["cmd.exe", "/c", "start", "whatsapp:"], shell=False)
        elif any(e in app_lower for e in ("explorer", "file", "folder")):
            subprocess.Popen(["explorer.exe"])
        elif any(p in app_lower for p in ("paint", "mspaint")):
            subprocess.Popen(["mspaint.exe"])
        else:
            subprocess.Popen(["cmd.exe", "/c", "start", "", app_clean], shell=False)

        time.sleep(2.0)

        # 5. FINAL STRICT VERIFICATION
        hwnd, title = _find_window_hwnd(app_clean)
        if hwnd:
            focus_window(app_clean)
            return f"Verified: Successfully launched '{title}' on your screen."
        else:
            return f"Verification failed: Searched for '{app_name}' in the taskbar search bar and launched it, but no visible window could be detected on screen."

    except Exception as e:
        return f"Error launching {app_name}: {e}"


def _open_url(url: str) -> str:
    """Opens a website in Google Chrome or default browser."""
    try:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        _launch_browser_url(url)
        return f"Opened {url} in browser."
    except Exception as e:
        return f"Error opening URL {url}: {e}"


def _play_music(query: str = "") -> str:
    """Searches and directly plays the requested music/video on YouTube in Google Chrome like a real human user."""
    clean_query = query.strip() if query else "tamil songs"
    for prefix in ["open chrome and play", "play some", "play"]:
        if clean_query.lower().startswith(prefix):
            clean_query = clean_query[len(prefix):].strip()
    if not clean_query:
        clean_query = "tamil songs"

    def _worker():
        try:
            import urllib.request
            import urllib.parse
            import re
            from window_manager import focus_window, attach_desktop

            # 1. Resolve top YouTube watch video URL directly
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_query)}"
            req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore")
            video_ids = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html)

            if video_ids:
                play_url = f"https://www.youtube.com/watch?v={video_ids[0]}"
            else:
                play_url = search_url

            # 2. Launch directly in Chrome via Chrome executable
            _launch_browser_url(play_url)
            print(f"[PLAY_MUSIC SUCCESS]: Now playing '{clean_query}' ({play_url})")

            # 3. Wait for video player page to load
            time.sleep(3.5)
            focus_window("Chrome")
            time.sleep(0.4)

            # 4. Guarantee playback is active and volume is audible
            import pyautogui
            pyautogui.FAILSAFE = False
            with attach_desktop():
                w, h = pyautogui.size()
                pyautogui.click(w // 2, int(h * 0.45))
                time.sleep(0.2)
                pyautogui.press('space')
                time.sleep(0.2)
                for _ in range(5):
                    pyautogui.press('up')
                    time.sleep(0.05)
        except Exception as e:
            print(f"[PLAY_MUSIC BACKGROUND ERROR]: {e}")

    threading.Thread(target=_worker, daemon=True).start()
    return f"Opening YouTube in Google Chrome and starting playback for '{clean_query}'."


def _search_web(query: str) -> str:
    """Searches Google for the given query in the web browser."""
    try:
        encoded = urllib.parse.quote_plus(query)
        _launch_browser_url(f"https://www.google.com/search?q={encoded}")
        return f"Searched Google for '{query}'."
    except Exception as e:
        return f"Error searching Google: {e}"


class GeminiLiveDesktopCompanion:
    def __init__(self, model_name: str = LIVE_MODEL, enable_widget: bool = True, enable_camera: bool = True, enable_alert: bool = True):
        self.model_name = model_name
        self.client = genai.Client()
        self.running = False
        self.enable_camera = enable_camera
        self.enable_screen = True
        self.enable_alert = enable_alert
        self.mic_muted = False
        self.p_audio = pyaudio.PyAudio()
        self.audio_out_stream: Optional[pyaudio.Stream] = None
        self.audio_in_stream: Optional[pyaudio.Stream] = None
        self.widget = GeminiFloatingWidget(
            on_close=self.stop,
            on_toggle_camera=self.on_toggle_camera,
            on_toggle_screen=self.on_toggle_screen,
            on_toggle_alert=self.on_toggle_alert,
            on_toggle_mic=self.on_toggle_mic,
            initial_camera=self.enable_camera,
            initial_screen=self.enable_screen,
            initial_alert=self.enable_alert,
            initial_mic=not self.mic_muted,
        ) if enable_widget else None
        self.is_speaking = False
        self.send_lock = asyncio.Lock()
        self.current_turn_text = ""
        self.reset_task: Optional[asyncio.Task] = None

    def _schedule_idle_reset(self, delay: float = 4.5):
        """Retains the final spoken or action caption on the widget for `delay` seconds before resetting to Ready."""
        if self.reset_task and not self.reset_task.done():
            self.reset_task.cancel()

        async def _delayed_reset():
            try:
                await asyncio.sleep(delay)
                if not self.is_speaking and self.widget and self.widget.current_state not in ("working", "talking"):
                    mode_lbl = "Live Vision" if self.enable_screen else "Voice Only"
                    self.widget.set_state("idle", f"Gemini Live Ready ({mode_lbl})")
                    self.current_turn_text = ""
            except asyncio.CancelledError:
                pass

        self.reset_task = asyncio.create_task(_delayed_reset())

    def on_toggle_camera(self, is_on: bool):
        self.enable_camera = is_on
        if is_on:
            try:
                _camera_mgr.start_stream()
            except Exception:
                pass
        else:
            try:
                _camera_mgr.stop_stream()
            except Exception:
                pass
        print(f"[TOGGLE] Camera {'ENABLED' if is_on else 'DISABLED'}")

    def on_toggle_screen(self, is_on: bool):
        self.enable_screen = is_on
        mode = "Live Vision (Screen+Cam)" if is_on else "Ultra-Fast Pure Voice Mode"
        print(f"[TOGGLE] Mode switched to: {mode}")

    def on_toggle_alert(self, is_on: bool):
        self.enable_alert = is_on
        print(f"[TOGGLE] Proactive distraction watchdog {'ENABLED' if is_on else 'DISABLED'}")

    def on_toggle_mic(self, is_on: bool):
        self.mic_muted = not is_on
        print(f"[TOGGLE] Microphone {'UNMUTED' if is_on else 'MUTED'}")

    def _setup_audio(self):
        """Initializes PyAudio input (mic) and output (speakers) streams."""
        try:
            self.audio_out_stream = self.p_audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=AUDIO_OUT_RATE,
                output=True,
                frames_per_buffer=2048,
            )
            self.audio_in_stream = self.p_audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=AUDIO_IN_RATE,
                input=True,
                frames_per_buffer=AUDIO_IN_CHUNK,
            )
            print("[INFO] Audio hardware initialized (Mic: 16kHz, Speakers: 24kHz).")
        except Exception as e:
            print(f"[WARN] Failed to initialize live audio hardware: {e}")

    def _capture_screen_frame(self) -> Optional[types.Blob]:
        """Captures primary desktop and composites laptop camera PiP for live streaming."""
        try:
            img, _, _ = _screenshot_win32_ctypes()
            img.thumbnail((FRAME_WIDTH, FRAME_HEIGHT), Image.Resampling.BILINEAR)
            if self.enable_camera:
                try:
                    img = overlay_camera_pip(img, position="bottom-right")
                except Exception:
                    pass
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=55, optimize=True)
            return types.Blob(data=buf.getvalue(), mime_type="image/jpeg")
        except Exception as e:
            print(f"[ERROR] Screen capture error: {e}")
            return None

    async def _stream_screen_loop(self, session):
        """Continuously captures desktop at 1 FPS and sends video frames when screen vision is enabled."""
        print(f"[LIVE VISION] Video streamer ready ({SCREEN_FPS} FPS, {FRAME_WIDTH}x{FRAME_HEIGHT})...")
        while self.running:
            try:
                if not self.enable_screen:
                    # In Pure Voice Mode: skip video completely for blazing <300ms speed!
                    await asyncio.sleep(0.4)
                    continue

                if self.is_speaking:
                    # While Gemini is actively speaking back to user, pause screen frame transmission
                    # so audio playback has 100% bandwidth and zero stutter or interruption!
                    await asyncio.sleep(0.3)
                    continue

                frame_blob = self._capture_screen_frame()
                if frame_blob is not None:
                    async with self.send_lock:
                        await session.send_realtime_input(media=frame_blob)
                await asyncio.sleep(1.0 / SCREEN_FPS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("closed", "timeout", "1011", "1006", "internal error")):
                    break
                print(f"[WARN in screen loop]: {e}")
                await asyncio.sleep(1.0)

    async def _stream_mic_loop(self, session):
        """Streams microphone PCM audio chunks in real-time."""
        if not self.audio_in_stream:
            return
        print("[LIVE AUDIO] Microphone live stream active. Speak naturally...")
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                if self.mic_muted:
                    await asyncio.sleep(0.1)
                    continue

                data = await loop.run_in_executor(
                    None,
                    self.audio_in_stream.read,
                    AUDIO_IN_CHUNK,
                    False,
                )
                if data:
                    blob = types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    async with self.send_lock:
                        await session.send_realtime_input(audio=blob)
                    # Voice activity detection for widget indicator
                    if self.widget and len(data) >= 128:
                        try:
                            peak = max(abs(int.from_bytes(data[i:i+2], byteorder='little', signed=True)) for i in range(0, min(len(data), 256), 16))
                            if peak > 1500 and self.widget.current_state not in ("talking", "working"):
                                self.widget.set_state("listening", "Listening to your voice...")
                        except Exception:
                            pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("closed", "timeout", "1011", "1006", "internal error")):
                    break
                await asyncio.sleep(0.1)

    async def _proactive_watchdog_loop(self, session):
        """Periodically checks if user is distracted by phone/reels and proactively alerts them."""
        await asyncio.sleep(15.0)
        while self.running:
            try:
                await asyncio.sleep(40.0)
                if not self.running:
                    break
                if not self.enable_alert or not self.enable_screen:
                    continue
                if self.is_speaking:
                    continue

                check_turn = types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "[PROACTIVE FOCUS MONITOR]: Look closely at the latest video frame, particularly the green-bordered laptop webcam PiP box in the bottom-right and the active desktop. "
                                "Is the user currently holding a mobile phone, looking down scrolling reels/social media, watching distracting content, or away from their work? "
                                "If YES: Speak aloud directly through the laptop speakers with an encouraging but firm wake-up call to Nandha to put down the phone and refocus! "
                                "If NO (user is studying, typing code, reading, or working): Stay completely silent and do not speak."
                            )
                        )
                    ]
                )
                async with self.send_lock:
                    await session.send_client_content(turns=check_turn, turn_complete=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("closed", "timeout", "1011", "1006")):
                    break
                await asyncio.sleep(5.0)

    async def _receive_loop(self, session):
        """Receives live model responses (audio to speakers + real-time text transcription + tool calls)."""
        print("[READY] Connected to Gemini Live! Gemini can now see your screen and hear your voice.\n")
        try:
            async for response in session.receive():
                if not self.running:
                    break

                server_content = response.server_content
                if server_content is not None:
                    # 1. Real-time User Input Speech Transcription
                    if hasattr(server_content, "interim_input_transcription") and server_content.interim_input_transcription:
                        user_text = getattr(server_content.interim_input_transcription, "text", "")
                        if user_text and user_text.strip():
                            if self.reset_task and not self.reset_task.done():
                                self.reset_task.cancel()
                            self.current_turn_text = ""
                            if self.widget:
                                self.widget.set_state("listening", f"You: {user_text.strip()}")

                    if hasattr(server_content, "input_transcription") and server_content.input_transcription:
                        user_final = getattr(server_content.input_transcription, "text", "")
                        if user_final and user_final.strip():
                            print(f"\n[USER SPEECH]: {user_final.strip()}", flush=True)
                            if self.reset_task and not self.reset_task.done():
                                self.reset_task.cancel()
                            self.current_turn_text = ""
                            if self.widget:
                                self.widget.set_state("thinking", f"You: {user_final.strip()}")

                    # 2. Real-time Model Speech Audio & Streaming Subtitles
                    model_turn = server_content.model_turn
                    if model_turn is not None:
                        self.is_speaking = True
                        for part in model_turn.parts:
                            # Output audio to speakers asynchronously without blocking event loop
                            if part.inline_data and self.audio_out_stream:
                                loop = asyncio.get_running_loop()
                                await loop.run_in_executor(None, self.audio_out_stream.write, part.inline_data.data)

                            # Stream text chunks to terminal and widget subtitle
                            if part.text:
                                try:
                                    print(part.text, end="", flush=True)
                                except Exception:
                                    pass
                                self.current_turn_text += part.text
                                if self.widget:
                                    self.widget.set_state("talking", f"Gemini: {self.current_turn_text.strip()}")

                    # Model output transcription attribute fallback
                    if hasattr(server_content, "output_transcription") and server_content.output_transcription:
                        out_text = getattr(server_content.output_transcription, "text", "")
                        if out_text and out_text.strip() and out_text not in self.current_turn_text:
                            self.current_turn_text += out_text
                            if self.widget:
                                self.widget.set_state("talking", f"Gemini: {self.current_turn_text.strip()}")

                    # Interruption handling
                    if getattr(server_content, "interrupted", False):
                        self.is_speaking = False
                        self.current_turn_text = ""
                        if self.widget:
                            self.widget.set_state("listening", "Listening...")

                    # Turn complete: retain final subtitle for 4.5s
                    if server_content.turn_complete:
                        self.is_speaking = False
                        print()  # newline after complete turn
                        self._schedule_idle_reset(4.5)

                # 3. Handle Live Tool Calls
                tool_call = response.tool_call
                if tool_call is not None:
                    for call in tool_call.function_calls:
                        name = call.name
                        args = call.args or {}
                        call_id = call.id if (call.id and str(call.id).strip() != "") else f"call_{int(time.time()*1000)}"
                        print(f"\n[LIVE TOOL CALL] {name}({args}) [id={call_id}]")
                        if self.widget:
                            self.widget.set_state("working", f"Performing: {name}...")

                        # Execute live action in executor so event loop is never blocked
                        result_content = "ok"
                        loop = asyncio.get_running_loop()
                        try:
                            if name == "open_application":
                                res = await loop.run_in_executor(None, _open_application, args.get("app_name", ""))
                                result_content = str(res)
                            elif name == "play_music":
                                res = await loop.run_in_executor(None, _play_music, args.get("query", ""))
                                result_content = str(res)
                            elif name == "open_url":
                                res = await loop.run_in_executor(None, _open_url, args.get("url", ""))
                                result_content = str(res)
                            elif name == "search_web":
                                res = await loop.run_in_executor(None, _search_web, args.get("query", ""))
                                result_content = str(res)
                            elif name == "click_mouse":
                                res = await loop.run_in_executor(
                                    None,
                                    lambda: click_mouse(
                                        x=args.get("x"),
                                        y=args.get("y"),
                                        button=args.get("button", "left"),
                                        clicks=args.get("clicks", 1),
                                    )
                                )
                                result_content = str(res)
                            elif name == "move_mouse":
                                res = await loop.run_in_executor(
                                    None,
                                    lambda: move_mouse(
                                        x=args.get("x", 0),
                                        y=args.get("y", 0),
                                    )
                                )
                                result_content = str(res)
                            elif name == "type_text":
                                res = await loop.run_in_executor(
                                    None,
                                    lambda: type_text(
                                        text=args.get("text", ""),
                                        interval=args.get("interval", 0.02),
                                    )
                                )
                                result_content = str(res)
                            elif name == "press_key":
                                res = await loop.run_in_executor(
                                    None,
                                    lambda: press_key(
                                        key=args.get("key", ""),
                                        presses=args.get("presses", 1),
                                    )
                                )
                                result_content = str(res)
                            elif name == "scroll_screen":
                                res = await loop.run_in_executor(
                                    None,
                                    lambda: scroll_screen(
                                        x=args.get("x", 500),
                                        y=args.get("y", 500),
                                        clicks=args.get("clicks", 3),
                                        direction=args.get("direction", "down"),
                                    )
                                )
                                result_content = str(res)
                            elif name == "focus_window":
                                res = await loop.run_in_executor(
                                    None,
                                    focus_window,
                                    args.get("title_substring", "")
                                )
                                result_content = str(res)
                            elif name == "get_active_window":
                                res = await loop.run_in_executor(None, get_active_window)
                                result_content = str(res)
                            elif name == "execute_action_plan":
                                res = await loop.run_in_executor(
                                    None,
                                    execute_action_plan,
                                    args.get("steps", []),
                                    args.get("plan_description", "")
                                )
                                result_content = str(res)
                            else:
                                result_content = f"Unknown tool: {name}"
                        except Exception as e:
                            result_content = f"Error executing {name}: {e}"

                        print(f"[TOOL RESULT]: {result_content}")

                        # Send tool response back to live session with lock
                        try:
                            async with self.send_lock:
                                await session.send_tool_response(
                                    function_responses=[
                                        types.FunctionResponse(
                                            name=name,
                                            id=call_id,
                                            response={"result": result_content},
                                        )
                                    ]
                                )
                        except Exception as e_resp:
                            print(f"[TOOL RESPONSE NOTICE]: {e_resp}")

                        if self.widget:
                            self.widget.set_state("working", f"Finished {name}")
        except Exception as e:
            err = str(e).lower()
            if not any(x in err for x in ("closed", "timeout", "1011", "1006")):
                print(f"[RECEIVE NOTICE]: {e}")

    async def start(self):
        """Main async entry point for the Gemini Live session with auto-reconnect."""
        self.running = True
        self._setup_audio()
        if self.enable_camera:
            try:
                _camera_mgr.start_stream()
            except Exception as e:
                print(f"[WARN] Could not initialize camera stream: {e}")

        # Tools Gemini Live can call while watching the screen
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="play_music",
                        description="Searches YouTube and plays music, songs, or videos in Google Chrome with automatic playback and unmute.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "query": types.Schema(type="STRING", description="Song name, artist, genre, or mood to play (e.g. 'tamil songs', 'lofi beats')")
                            },
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="open_application",
                        description="Launches or switches to a Windows desktop application (e.g. 'chrome', 'notepad', 'calc', 'spotify', 'code', 'explorer'). If user wants music, call play_music instead.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "app_name": types.Schema(type="STRING", description="Name of the application to launch (e.g. chrome, notepad)")
                            },
                            required=["app_name"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="open_url",
                        description="Opens any website URL in Google Chrome.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "url": types.Schema(type="STRING", description="Full URL to open (e.g. https://youtube.com)")
                            },
                            required=["url"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="search_web",
                        description="Searches Google for any query in Google Chrome.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "query": types.Schema(type="STRING", description="Search keywords or question")
                            },
                            required=["query"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="click_mouse",
                        description="Clicks the mouse at specified (x, y) coordinates on screen, or at current cursor position.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "x": types.Schema(type="INTEGER", description="X coordinate on screen"),
                                "y": types.Schema(type="INTEGER", description="Y coordinate on screen"),
                                "button": types.Schema(type="STRING", description="'left' or 'right' (default 'left')"),
                                "clicks": types.Schema(type="INTEGER", description="1 for single click, 2 for double click"),
                            },
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="move_mouse",
                        description="Moves the mouse cursor to (x, y) coordinates on screen.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "x": types.Schema(type="INTEGER", description="Target X coordinate"),
                                "y": types.Schema(type="INTEGER", description="Target Y coordinate"),
                            },
                            required=["x", "y"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="type_text",
                        description="Types text via simulated keyboard into the active focused window or input field.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "text": types.Schema(type="STRING", description="Text to type")
                            },
                            required=["text"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="press_key",
                        description="Presses a keyboard key (e.g. 'enter', 'space', 'esc', 'tab', 'win') or key combination (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'ctrl+t').",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "key": types.Schema(type="STRING", description="Key or combination to press")
                            },
                            required=["key"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="scroll_screen",
                        description="Scrolls mouse wheel up or down at specified coordinates.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "clicks": types.Schema(type="INTEGER", description="Number of scroll steps"),
                                "direction": types.Schema(type="STRING", description="'up' or 'down'"),
                            },
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="focus_window",
                        description="Brings any window matching the title substring to the foreground.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "title_substring": types.Schema(type="STRING", description="Window title to focus")
                            },
                            required=["title_substring"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_active_window",
                        description="Returns details about the currently active foreground window.",
                        parameters=types.Schema(type="OBJECT", properties={}),
                    ),
                    types.FunctionDeclaration(
                        name="execute_action_plan",
                        description="Executes sequence of mouse clicks, key presses, or text typing on screen.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "plan_description": types.Schema(type="STRING", description="What this action does"),
                                "steps": types.Schema(
                                    type="ARRAY",
                                    items=types.Schema(type="OBJECT"),
                                    description="List of action dicts (move, click, type, key, wait)",
                                ),
                            },
                            required=["steps"],
                        ),
                    ),
                ]
            )
        ]

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
            system_instruction=types.Content(
                parts=[
                    types.Part.from_text(
                        text=(
                            "You are Gemini Live, an autonomous real-time AI desktop companion for Nandha on Windows. "
                            "You have full human-like agency on this desktop: you can see the screen and laptop webcam, hear Nandha's voice, speak aloud through the laptop speakers, and control the computer like a human user. "
                            "\nVISION FEED: "
                            "- The video feed shows the full Windows desktop, plus Nandha's laptop camera in the bottom-right corner (in an emerald green PiP box). "
                            "- You CAN see Nandha directly through this camera. When asked if you can see him or what he is doing, confirm and describe accurately what you observe. "
                            "- Never assume or falsely claim that Nandha is using a phone or distracted unless he explicitly asks what you see. Be respectful, helpful, and attentive. "
                            "\nHUMAN-LIKE DESKTOP AUTOMATION RULES: "
                            "- When asked to play music or songs (e.g., 'play music', 'play songs', 'open chrome and play music', or any Tamil/English song request), ALWAYS call `play_music(query=...)`. This automatically opens Chrome and plays the song with audible sound. NEVER merely open Chrome and stop! "
                            "- When asked to open an app (e.g., Notepad, Calculator, Chrome, VS Code), ALWAYS call `open_application(app_name=...)`. This searches the Windows taskbar like a human, opens it, and verifies its window on screen. "
                            "- STRICT VERIFICATION MANDATE: When you call a tool, ALWAYS speak the truth of the tool result! If the tool result confirms 'Verified:', state that the app is open on screen. If the tool result says 'Verification failed:', honestly tell Nandha that you searched for it on the taskbar but the window did not open. NEVER claim an app is open unless the tool verifies it! Also look at the screen video feed in front of you to visually confirm. "
                            "- When asked to click, type, or press keys, use `click_mouse`, `type_text`, `press_key`, or `scroll_screen`. "
                            "- When asked to do something on screen, DO IT using your tools rather than just describing it. "
                            "\nCONVERSATION STYLE: "
                            "- Speak naturally, briskly, and warmly in 1 to 2 crisp sentences. "
                            "- Understand and respond in English and Tamil as spoken by the user. "
                            "- Do not give long monologues or say 'I have finished' without having actually run the tool."
                        )
                    )
                ]
            ),
            input_audio_transcription=types.AudioTranscriptionConfig() if hasattr(types, "AudioTranscriptionConfig") else True,
            output_audio_transcription=types.AudioTranscriptionConfig() if hasattr(types, "AudioTranscriptionConfig") else True,
            tools=tools,
        )

        while self.running:
            try:
                print(f"[CONNECTING] Opening bidirectional live stream with {self.model_name}...")
                async with self.client.aio.live.connect(model=self.model_name, config=config) as session:
                    tasks = [
                        asyncio.create_task(self._stream_screen_loop(session), name="ScreenStream"),
                        asyncio.create_task(self._stream_mic_loop(session), name="MicStream"),
                        asyncio.create_task(self._receive_loop(session), name="ReceiveLoop"),
                        asyncio.create_task(self._proactive_watchdog_loop(session), name="Watchdog"),
                    ]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        try:
                            t.result()
                        except Exception as e:
                            print(f"[TASK EXIT: {t.get_name()}]: {e}")
                    for t in pending:
                        t.cancel()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self.running:
                    break
                delay = 8.0 if "quota" in str(e).lower() else 2.0
                print(f"[AUTO-RECONNECT] Connection closed ({e}). Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)

    def stop(self):
        """Stops the live stream, widget, camera, and releases audio hardware."""
        if not self.running:
            return
        self.running = False
        if self.enable_camera:
            try:
                _camera_mgr.stop_stream()
            except Exception:
                pass
        w = self.widget
        self.widget = None
        if w:
            try:
                w.stop()
            except Exception:
                pass
        if self.audio_out_stream:
            try:
                self.audio_out_stream.stop_stream()
                self.audio_out_stream.close()
            except Exception:
                pass
            self.audio_out_stream = None
        if self.audio_in_stream:
            try:
                self.audio_in_stream.stop_stream()
                self.audio_in_stream.close()
            except Exception:
                pass
            self.audio_in_stream = None
        try:
            self.p_audio.terminate()
        except Exception:
            pass
        print("\n[STOPPED] Gemini Live Desktop Companion session ended.")


if __name__ == "__main__":
    companion = GeminiLiveDesktopCompanion()
    try:
        asyncio.run(companion.start())
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        companion.stop()
