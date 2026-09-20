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
from typing import Optional

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
    from .screen_vision import _screenshot_win32_ctypes, execute_action_plan
    from .window_manager import focus_window, get_active_window
except (ImportError, ValueError):
    from screen_vision import _screenshot_win32_ctypes, execute_action_plan
    from window_manager import focus_window, get_active_window

# Live Audio Specs
AUDIO_IN_RATE = 16000
AUDIO_IN_CHUNK = 1024
AUDIO_OUT_RATE = 24000

# Live Video Specs
SCREEN_FPS = 1.0  # 1 frame per second for optimal latency and bandwidth
FRAME_WIDTH = 1024
FRAME_HEIGHT = 576

# Available Live Native Audio Models
LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"


class GeminiLiveDesktopCompanion:
    def __init__(self, model_name: str = LIVE_MODEL):
        self.model_name = model_name
        self.client = genai.Client()
        self.running = False
        self.p_audio = pyaudio.PyAudio()
        self.audio_out_stream: Optional[pyaudio.Stream] = None
        self.audio_in_stream: Optional[pyaudio.Stream] = None

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

    def _capture_screen_frame(self) -> Optional[Image.Image]:
        """Captures primary desktop and resizes for live streaming."""
        try:
            img, _, _ = _screenshot_win32_ctypes()
            img.thumbnail((FRAME_WIDTH, FRAME_HEIGHT), Image.Resampling.BILINEAR)
            return img
        except Exception as e:
            print(f"[ERROR] Screen capture error: {e}")
            return None

    async def _stream_screen_loop(self, session):
        """Continuously captures desktop at 1 FPS and sends video frames over the WebSocket."""
        print(f"[LIVE VISION] Started screen video stream ({SCREEN_FPS} FPS, {FRAME_WIDTH}x{FRAME_HEIGHT})...")
        while self.running:
            try:
                frame = self._capture_screen_frame()
                if frame is not None:
                    await session.send_realtime_input(media=frame)
                await asyncio.sleep(1.0 / SCREEN_FPS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR in screen loop]: {e}")
                await asyncio.sleep(1.0)

    async def _stream_mic_loop(self, session):
        """Streams microphone PCM audio chunks in real-time."""
        if not self.audio_in_stream:
            return
        print("[LIVE AUDIO] Microphone live stream active. Speak naturally...")
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                data = await loop.run_in_executor(
                    None,
                    self.audio_in_stream.read,
                    AUDIO_IN_CHUNK,
                    False,
                )
                if data:
                    blob = types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    await session.send_realtime_input(audio=blob)
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(0.1)

    async def _receive_loop(self, session):
        """Receives live model responses (audio to speakers + real-time text transcription + tool calls)."""
        print("[READY] Connected to Gemini Live! Gemini can now see your screen and hear your voice.\n")
        async for response in session.receive():
            if not self.running:
                break

            server_content = response.server_content
            if server_content is not None:
                model_turn = server_content.model_turn
                if model_turn is not None:
                    for part in model_turn.parts:
                        # 1. Output audio to speakers
                        if part.inline_data and self.audio_out_stream:
                            self.audio_out_stream.write(part.inline_data.data)

                        # 2. Text transcription
                        if part.text:
                            print(part.text, end="", flush=True)

                if server_content.turn_complete:
                    print()  # newline after complete turn

            # 3. Handle Live Tool Calls
            tool_call = response.tool_call
            if tool_call is not None:
                for call in tool_call.function_calls:
                    name = call.name
                    args = call.args or {}
                    call_id = call.id
                    print(f"\n[LIVE TOOL CALL] {name}({args})")

                    # Execute live action
                    result_content = "ok"
                    try:
                        if name == "focus_window":
                            res = focus_window(args.get("title_substring", ""))
                            result_content = str(res)
                        elif name == "get_active_window":
                            res = get_active_window()
                            result_content = str(res)
                        elif name == "execute_action_plan":
                            res = execute_action_plan(args.get("steps", []), args.get("plan_description", ""))
                            result_content = str(res)
                    except Exception as e:
                        result_content = f"Error: {e}"

                    # Send tool response back to live session
                    await session.send_tool_response(
                        function_responses=[
                            types.FunctionResponse(
                                name=name,
                                id=call_id,
                                response={"result": result_content},
                            )
                        ]
                    )

    async def start(self):
        """Main async entry point for the Gemini Live session."""
        self.running = True
        self._setup_audio()

        # Tools Gemini Live can call while watching the screen
        tools = [
            types.Tool(
                function_declarations=[
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
                        "You are Gemini Live Desktop Companion, an autonomous AI pair programmer and desktop assistant. "
                        "You have continuous live vision of the user's Windows computer desktop via video frames, and you hear their voice. "
                        "Speak concisely and naturally like a helpful pair programmer. "
                        "When the user asks you to interact with something on screen, you can use your tools to focus windows, click, and type."
                    )
                ]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig() if hasattr(types, "AudioTranscriptionConfig") else True,
            tools=tools,
        )

        print(f"[CONNECTING] Opening bidirectional live stream with {self.model_name}...")
        async with self.client.aio.live.connect(model=self.model_name, config=config) as session:
            tasks = [
                asyncio.create_task(self._stream_screen_loop(session)),
                asyncio.create_task(self._stream_mic_loop(session)),
                asyncio.create_task(self._receive_loop(session)),
            ]
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                pass
            finally:
                for t in tasks:
                    t.cancel()

    def stop(self):
        """Stops the live stream and releases audio hardware."""
        self.running = False
        if self.audio_out_stream:
            try:
                self.audio_out_stream.stop_stream()
                self.audio_out_stream.close()
            except Exception:
                pass
        if self.audio_in_stream:
            try:
                self.audio_in_stream.stop_stream()
                self.audio_in_stream.close()
            except Exception:
                pass
        self.p_audio.terminate()
        print("\n[STOPPED] Gemini Live Desktop Companion session ended.")


if __name__ == "__main__":
    companion = GeminiLiveDesktopCompanion()
    try:
        asyncio.run(companion.start())
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        companion.stop()
