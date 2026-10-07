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

    def __init__(self):
        # Timing thresholds (seconds)
        self.DOT_THRESHOLD = 0.35    # Blinks shorter than this are dots
        self.CHAR_GAP = 0.8          # Gap to finalize a character
        self.WORD_GAP = 1.8          # Gap to insert a word space
        self.SPEAK_GAP = 3.5         # Gap to trigger TTS on accumulated sentence

        # State
        self.lock = threading.RLock()
        self.enabled = True

        self.blink_start_time = None
        self.blink_end_time = None
        self.is_blinking = False

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

    def _init_tts(self):
        """Initialize text-to-speech engine in a background thread."""
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
                except Exception:
                    engine = None

            while True:
                text_to_speak = None
                with self.tts_lock:
                    if self.tts_queue:
                        text_to_speak = self.tts_queue.pop(0)

                if text_to_speak:
                    try:
                        if engine:
                            engine.say(text_to_speak)
                            engine.runAndWait()
                        else:
                            # Fallback: use espeak via subprocess
                            import subprocess
                            subprocess.run(
                                ["espeak", "-s", "140", text_to_speak],
                                timeout=10, capture_output=True
                            )
                    except Exception:
                        pass

                time.sleep(0.1)

        threading.Thread(target=_tts_worker, daemon=True).start()

    def speak(self, text):
        """Queue text for TTS playback."""
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

    def on_blink_end(self):
        """Called when a blink ends (eyes open). Determines dot or dash."""
        if not self.enabled:
            return

        with self.lock:
            if self.is_blinking and self.blink_start_time:
                self.is_blinking = False
                self.blink_end_time = time.time()
                duration = self.blink_end_time - self.blink_start_time
                self.last_blink_end = self.blink_end_time

                # Classify: dot or dash
                if duration < self.DOT_THRESHOLD:
                    self.current_symbol += "."
                    self.current_dots_dashes += "·"
                else:
                    self.current_symbol += "-"
                    self.current_dots_dashes += "−"

                self.blink_start_time = None

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
            return {
                "enabled": self.enabled,
                "is_blinking": self.is_blinking,
                "current_morse": self.current_symbol,
                "current_display": self.current_dots_dashes,
                "decoded_message": self.decoded_message,
                "last_char": self.last_decoded_char,
                "symbol_history": list(self.symbol_history[-10:]),
                "blink_duration": (
                    round(time.time() - self.blink_start_time, 2)
                    if self.is_blinking and self.blink_start_time
                    else 0
                ),
            }
