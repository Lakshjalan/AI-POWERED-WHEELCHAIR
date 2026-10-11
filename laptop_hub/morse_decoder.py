#!/usr/bin/env python3
"""
OcuSteer — Morse Code Blink Decoder
-------------------------------------
Decodes eye-blink patterns into Morse code and then into text.

Timing Protocol (configurable):
  - Blink duration < DOT_THRESHOLD  → DOT  (·)
  - Blink duration ≥ DOT_THRESHOLD  → DASH (−)
  - Gap between blinks > CHAR_GAP   → end of character
  - Gap between blinks > WORD_GAP   → end of word (space)

The decoded text is spoken aloud using pyttsx3 text-to-speech engine.
"""

import time
import threading

# Try to import pyttsx3 for TTS, fallback to espeak subprocess
try:
    import pyttsx3
    TTS_ENGINE_AVAILABLE = True
except ImportError:
    TTS_ENGINE_AVAILABLE = False

# International Morse Code mapping
MORSE_CODE_DICT = {
    '.-':     'A',  '-...':   'B',  '-.-.':   'C',  '-..':    'D',
    '.':      'E',  '..-.':   'F',  '--.':    'G',  '....':   'H',
    '..':     'I',  '.---':   'J',  '-.-':    'K',  '.-..':   'L',
    '--':     'M',  '-.':     'N',  '---':    'O',  '.--.':   'P',
    '--.-':   'Q',  '.-.':    'R',  '...':    'S',  '-':      'T',
    '..-':    'U',  '...-':   'V',  '.--':    'W',  '-..-':   'X',
    '-.--':   'Y',  '--..':   'Z',
    '-----':  '0',  '.----':  '1',  '..---':  '2',  '...--':  '3',
    '....-':  '4',  '.....':  '5',  '-....':  '6',  '--...':  '7',
    '---..':  '8',  '----.':  '9',
    '.-.-.-': '.',  '--..--': ',',  '..--..': '?',  '.----.': "'",
    '-.-.--': '!',  '-..-.':  '/',  '-.--.':  '(',  '-.--.-': ')',
    '.-...':  '&',  '---...': ':',  '-.-.-.': ';',  '-...-':  '=',
    '.-.-.':  '+',  '-....-': '-',  '..--.-': '_',  '.-..-.': '"',
    '...-..-':'$',  '.--.-.': '@',
}

# Reverse lookup: letter → morse
LETTER_TO_MORSE = {v: k for k, v in MORSE_CODE_DICT.items()}


class MorseDecoder:
    """
    Thread-safe Morse code decoder driven by blink events from the eye tracker.
    """

    def __init__(self, dot_threshold=0.35, min_blink_dur=0.10, char_gap=0.85, word_gap=2.0, speak_gap=4.0):
        # Configurable timing thresholds (seconds)
        self.MIN_BLINK_DURATION = min_blink_dur # Ignore blinks shorter than this (involuntary micro-blinks)
        self.DOT_THRESHOLD = dot_threshold      # Blinks shorter than this are dots (.), >= are dashes (-)
        self.MAX_BLINK_DURATION = 3.0           # Cap for dash classification
        self.CHAR_GAP = char_gap                # Gap to finalize a character
        self.WORD_GAP = word_gap                # Gap to insert a word space
        self.SPEAK_GAP = speak_gap              # Gap to trigger auto-TTS on accumulated sentence

        # State
        self.lock = threading.RLock()
        self.enabled = True

        self.blink_start_time = None
        self.blink_end_time = None
        self.is_blinking = False
        self.last_blink_duration = 0.0

        # Current symbol being built (e.g. ".-" for 'A')
        self.current_symbol = ""
        # Decoded message buffer
        self.decoded_message = ""
        # Last decoded character (for UI flash)
        self.last_decoded_char = ""
        # Visual buffer of dots/dashes for current symbol
        self.current_dots_dashes = ""
        # History of recent symbols for display
        self.symbol_history = []
        # Timestamp of last blink end (for gap detection)
        self.last_blink_end = 0
        # Whether a char gap has been processed since last blink
        self.char_gap_processed = False
        # Whether a word gap has been processed since last char
        self.word_gap_processed = False
        # Whether the speak gap has been processed
        self.speak_triggered = False

        # TTS engine (initialized in background thread)
        self.tts_lock = threading.Lock()
        self.tts_queue = []
        self._init_tts()

        # Start the gap-checker background thread
        self._gap_thread = threading.Thread(target=self._gap_checker_loop, daemon=True)
        self._gap_thread.start()

    def update_timings(self, dot_thresh=None, char_gap=None, word_gap=None, speak_gap=None, min_blink=None):
        """Allow runtime adjustment of timing thresholds."""
        with self.lock:
            if dot_thresh is not None:
                self.DOT_THRESHOLD = float(dot_thresh)
            if char_gap is not None:
                self.CHAR_GAP = float(char_gap)
            if word_gap is not None:
                self.WORD_GAP = float(word_gap)
            if speak_gap is not None:
                self.SPEAK_GAP = float(speak_gap)
            if min_blink is not None:
                self.MIN_BLINK_DURATION = float(min_blink)

    def _init_tts(self):
        """Initialize text-to-speech engine in a background thread with cross-platform fallbacks."""
        def _tts_worker():
            engine = None
            if TTS_ENGINE_AVAILABLE:
                try:
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 140)
                    engine.setProperty('volume', 0.95)
                    # Try to use a clear voice
                    voices = engine.getProperty('voices')
                    if voices and len(voices) > 1:
                        engine.setProperty('voice', voices[1].id)
                except Exception as e:
                    print(f"⚠️ pyttsx3 worker init notice: {e}")
                    engine = None

            while True:
                text_to_speak = None
                with self.tts_lock:
                    if self.tts_queue:
                        text_to_speak = self.tts_queue.pop(0)

                if text_to_speak:
                    spoken = False
                    if engine:
                        try:
                            engine.say(text_to_speak)
                            engine.runAndWait()
                            spoken = True
                        except Exception as e:
                            print(f"⚠️ pyttsx3 say error: {e}")
                    if not spoken:
                        # Fallback for Windows SAPI5 via PowerShell if available
                        try:
                            import subprocess
                            ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text_to_speak}')"
                            subprocess.run(["powershell", "-Command", ps_cmd], timeout=10, capture_output=True)
                            spoken = True
                        except Exception:
                            pass
                    if not spoken:
                        # Fallback for Linux espeak via subprocess
                        try:
                            import subprocess
                            subprocess.run(
                                ["espeak", "-s", "140", text_to_speak],
                                timeout=10, capture_output=True
                            )
                        except Exception:
                            pass

                time.sleep(0.08)

        threading.Thread(target=_tts_worker, daemon=True).start()

    def speak(self, text):
        """Queue text for non-blocking TTS playback."""
        if text and text.strip():
            with self.tts_lock:
                self.tts_queue.append(text.strip())

    def on_blink_start(self):
        """Called when a blink begins (eyes close)."""
        if not self.enabled:
            return

        with self.lock:
            if not self.is_blinking:
                self.is_blinking = True
                self.blink_start_time = time.time()
                self.char_gap_processed = False
                self.word_gap_processed = False
                self.speak_triggered = False

    def on_blink_end(self, explicit_duration=None):
        """Called when a blink ends (eyes open). Determines dot or dash."""
        if not self.enabled:
            return

        with self.lock:
            if self.is_blinking or explicit_duration is not None:
                self.blink_end_time = time.time()
                if explicit_duration is not None and explicit_duration > 0:
                    duration = explicit_duration
                elif self.blink_start_time:
                    duration = self.blink_end_time - self.blink_start_time
                else:
                    duration = 0.0

                self.is_blinking = False
                self.last_blink_duration = duration
                self.last_blink_end = self.blink_end_time
                self.blink_start_time = None

                # Involuntary micro-blink rejection (< min_blink_dur)
                if duration < self.MIN_BLINK_DURATION:
                    return

                # Classify: dot or dash
                if duration < self.DOT_THRESHOLD:
                    self.current_symbol += "."
                    self.current_dots_dashes += "·"
                else:
                    self.current_symbol += "-"
                    self.current_dots_dashes += "−"

    def _gap_checker_loop(self):
        """Background thread that checks for inter-symbol / inter-word gaps."""
        while True:
            if self.enabled:
                self._check_gaps()
            time.sleep(0.05)

    def _check_gaps(self):
        """Check elapsed time since last blink to finalize characters/words."""
        with self.lock:
            if self.is_blinking or self.last_blink_end == 0:
                return

            elapsed = time.time() - self.last_blink_end

            # Character gap: finalize current symbol
            if elapsed > self.CHAR_GAP and self.current_symbol and not self.char_gap_processed:
                self._finalize_character()
                self.char_gap_processed = True
                self.word_gap_processed = False
                self.speak_triggered = False

            # Word gap: insert space
            if elapsed > self.WORD_GAP and not self.word_gap_processed and self.char_gap_processed:
                if self.decoded_message and not self.decoded_message.endswith(" "):
                    self.decoded_message += " "
                self.word_gap_processed = True

            # Speak gap: TTS the accumulated message
            if elapsed > self.SPEAK_GAP and not self.speak_triggered and self.decoded_message.strip():
                self.speak(self.decoded_message.strip())
                self.speak_triggered = True

    def _finalize_character(self):
        """Decode the current Morse symbol into a character."""
        if not self.current_symbol:
            return

        decoded = MORSE_CODE_DICT.get(self.current_symbol, "?")
        self.last_decoded_char = decoded

        # Add to history
        self.symbol_history.append({
            "morse": self.current_symbol,
            "display": self.current_dots_dashes,
            "char": decoded,
            "time": time.time()
        })

        # Keep history bounded
        if len(self.symbol_history) > 30:
            self.symbol_history.pop(0)

        # Append to message
        self.decoded_message += decoded

        # Reset current symbol
        self.current_symbol = ""
        self.current_dots_dashes = ""

    def clear_message(self):
        """Clear the decoded message buffer."""
        with self.lock:
            self.decoded_message = ""
            self.last_decoded_char = ""
            self.current_symbol = ""
            self.current_dots_dashes = ""
            self.symbol_history.clear()
            self.last_blink_end = 0
            self.char_gap_processed = False
            self.word_gap_processed = False
            self.speak_triggered = False

    def speak_now(self):
        """Immediately speak the current message via TTS."""
        with self.lock:
            msg = self.decoded_message.strip()
        if msg:
            self.speak(msg)
        return msg

    def get_state(self):
        """Return the current decoder state for the UI."""
        with self.lock:
            now = time.time()
            if self.is_blinking and self.blink_start_time:
                dur = round(now - self.blink_start_time, 2)
            else:
                dur = round(self.last_blink_duration, 2)

            return {
                "enabled": self.enabled,
                "is_blinking": self.is_blinking,
                "blink_state": "CLOSED" if self.is_blinking else "OPEN",
                "blink_duration": dur,
                "current_morse": self.current_symbol,
                "current_display": self.current_dots_dashes,
                "decoded_message": self.decoded_message,
                "last_char": self.last_decoded_char,
                "symbol_history": list(self.symbol_history[-10:]),
                "dot_threshold": self.DOT_THRESHOLD,
                "char_gap": self.CHAR_GAP,
                "word_gap": self.WORD_GAP,
                "speak_gap": self.SPEAK_GAP,
                "status": "LISTENING" if self.enabled else "STANDBY"
            }
