"""The full-screen, distraction-free editor (the only module that uses prompt_toolkit).

Layout, top to bottom::

    ┌──────────────────────────────────────────────┐
    │          ┌──────── width ────────┐           │
    │          │ your text, soft-      │           │  <- centered column
    │          │ wrapped at word ends  │           │
    │          └───────────────────────┘           │
    │ essay · 812 words · +210 this session · ...  │  <- status line (Ctrl-T)
    └──────────────────────────────────────────────┘

All decisions (what "dirty" means, when to commit, what the status line says)
live in :class:`drafts.session.WritingSession`. This module only wires keys and
timers to it, which is why the editor itself needs very little testing beyond
a smoke test that drives it with fake keystrokes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Dimension,
    FormattedTextControl,
    HorizontalAlign,
    HSplit,
    Layout,
    ScrollOffsets,
    VSplit,
    Window,
)
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from drafts.session import WritingSession

DEFAULT_WIDTH = 72
TAB = "    "

STYLE = Style.from_dict(
    {
        "status": "fg:ansibrightblack",
        "status.unsaved": "fg:ansiyellow",
        "status.prompt": "fg:ansiyellow bold",
    }
)

HELP = "Ctrl-S save · Ctrl-Q quit · Ctrl-T toggle status"


@dataclass
class EditorOptions:
    width: int = DEFAULT_WIDTH
    show_status: bool = True
    typewriter: bool = False


@dataclass
class EditorResult:
    """How the session ended, for the CLI to report."""

    saved: bool  # False if the user chose "quit without saving"
    commit: str | None  # commit made when closing, if any


class Editor:
    """Builds and runs the prompt_toolkit application for one session."""

    def __init__(self, session: WritingSession, options: EditorOptions | None = None) -> None:
        self.session = session
        self.options = options or EditorOptions()
        self.show_status = self.options.show_status
        self.confirming_quit = False
        self.session.notify(HELP)

        self.buffer = Buffer(
            document=Document(session.text, cursor_position=len(session.text)),
            multiline=True,
            on_text_changed=lambda buf: session.update(buf.text),
        )

    # ----------------------------------------------------------------- layout

    def _status_fragments(self) -> list[tuple[str, str]]:
        if self.confirming_quit:
            return [
                (
                    "class:status.prompt",
                    " Unsaved changes. Save before quitting? [y]es / [n]o / [c]ancel",
                )
            ]
        style = "class:status.unsaved" if self.session.dirty else "class:status"
        text = " " + self.session.status_line()
        if message := self.session.current_message():
            text += "  ·  " + message
        return [(style, text)]

    def _text_window(self) -> Window:
        width = self.options.width
        offsets = ScrollOffsets()
        if self.options.typewriter:
            # Keep about half the screen above and below the cursor line so the
            # line being written stays near the middle, like a typewriter.
            half = lambda: max(0, self._rows() // 2 - 1)  # noqa: E731
            offsets = ScrollOffsets(top=half, bottom=half)
        return Window(
            BufferControl(buffer=self.buffer),
            width=Dimension(min=min(20, width), max=width, preferred=width),
            wrap_lines=True,
            scroll_offsets=offsets,
            allow_scroll_beyond_bottom=self.options.typewriter,
        )

    def _rows(self) -> int:
        try:
            return self.app.output.get_size().rows
        except Exception:  # output not ready yet
            return 24

    def build(self, input: Input | None = None, output: Output | None = None) -> Application:
        """Create the Application. ``input``/``output`` are injectable for tests."""
        status_visible = Condition(lambda: self.show_status or self.confirming_quit)
        root = HSplit(
            [
                Window(height=1),  # a blank line of breathing room at the top
                VSplit([self._text_window()], align=HorizontalAlign.CENTER),
                ConditionalContainer(
                    Window(FormattedTextControl(self._status_fragments), height=1),
                    filter=status_visible,
                ),
            ]
        )
        self.app: Application[EditorResult] = Application(
            layout=Layout(root),
            key_bindings=self._key_bindings(),
            style=STYLE,
            full_screen=True,
            mouse_support=False,
            refresh_interval=1.0,  # keeps the clock in the status line current
            input=input,
            output=output,
        )
        # prompt_toolkit's Emacs bindings include chords that start with Ctrl-X
        # (e.g. Ctrl-X Ctrl-U), so by default it waits a full second after
        # Ctrl-X to see if a chord follows. We use Ctrl-X to quit, so shorten
        # that wait to keep quitting instant.
        self.app.timeoutlen = 0.05
        self.app.pre_run_callables.append(self._start_autosave)
        return self.app

    # ------------------------------------------------------------------- keys

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        confirming = Condition(lambda: self.confirming_quit)

        @kb.add("c-s", filter=~confirming)
        def _save(event: KeyPressEvent) -> None:
            self.session.save()

        @kb.add("c-q", filter=~confirming)
        @kb.add("c-x", filter=~confirming)
        def _quit(event: KeyPressEvent) -> None:
            if self.session.dirty:
                self.confirming_quit = True
            else:
                self._exit(save=True)

        @kb.add("c-t", filter=~confirming)
        def _toggle_status(event: KeyPressEvent) -> None:
            self.show_status = not self.show_status

        @kb.add("tab", filter=~confirming)
        def _indent(event: KeyPressEvent) -> None:
            event.current_buffer.insert_text(TAB)

        @kb.add("y", filter=confirming)
        @kb.add("Y", filter=confirming)
        def _confirm_save(event: KeyPressEvent) -> None:
            self._exit(save=True)

        @kb.add("n", filter=confirming)
        @kb.add("N", filter=confirming)
        def _confirm_discard(event: KeyPressEvent) -> None:
            self._exit(save=False)

        @kb.add("c", filter=confirming)
        @kb.add("C", filter=confirming)
        @kb.add("escape", filter=confirming)
        def _cancel(event: KeyPressEvent) -> None:
            self.confirming_quit = False

        @kb.add("<any>", filter=confirming)
        def _swallow(event: KeyPressEvent) -> None:
            """While asking y/n/c, other keys must not edit the text."""

        return kb

    def _exit(self, save: bool) -> None:
        # Write now (fast, local) but leave the git commit to run(), after the
        # screen has been restored, so quitting feels instant.
        if save:
            self.session.write()
        self.app.exit(result=EditorResult(saved=save, commit=None))

    # --------------------------------------------------------------- autosave

    def _start_autosave(self) -> None:
        self.app.create_background_task(self._autosave_loop())

    async def _autosave_loop(self) -> None:
        """Check once a second; the session decides whether a write is due."""
        while True:
            await asyncio.sleep(1.0)
            if self.session.autosave():
                self.app.invalidate()

    # -------------------------------------------------------------------- run

    def run(self, input: Input | None = None, output: Output | None = None) -> EditorResult:
        """Run the editor until the user quits, then commit the session."""
        app = self.build(input=input, output=output)
        result = app.run()
        commit = self.session.finish(save=result.saved)
        return EditorResult(saved=result.saved, commit=commit)
