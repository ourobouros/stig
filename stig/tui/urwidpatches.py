# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details
# http://www.gnu.org/licenses/gpl-3.0.txt

"""Monkey patches that should be removed when they are resolved upstream"""

import urwid

# Add more actions for key bindings
urwid.CURSOR_WORD_LEFT         = 'cursor word left'
urwid.CURSOR_WORD_RIGHT        = 'cursor word right'
urwid.DELETE_TO_EOL            = 'delete to end of line'
urwid.DELETE_LINE              = 'delete line'
urwid.DELETE_CHAR_UNDER_CURSOR = 'delete char under cursor'
urwid.DELETE_WORD_LEFT         = 'delete word left'
urwid.DELETE_WORD_RIGHT        = 'delete word right'
urwid.CANCEL                   = 'cancel'

# Remove urwid's default keybindings and create our own built-in command_map
for key in tuple(urwid.command_map._command):
    del urwid.command_map._command[key]

from .keymap import Key
urwid.command_map[Key('pgup')]           = urwid.CURSOR_PAGE_UP
urwid.command_map[Key('pgdn')]           = urwid.CURSOR_PAGE_DOWN
urwid.command_map[Key('ctrl-b')]         = urwid.CURSOR_PAGE_UP
urwid.command_map[Key('ctrl-f')]         = urwid.CURSOR_PAGE_DOWN
urwid.command_map[Key('b')]              = urwid.CURSOR_PAGE_UP
urwid.command_map[Key('space')]          = urwid.CURSOR_PAGE_DOWN

urwid.command_map[Key('up')]             = urwid.CURSOR_UP
urwid.command_map[Key('down')]           = urwid.CURSOR_DOWN
urwid.command_map[Key('left')]           = urwid.CURSOR_LEFT
urwid.command_map[Key('right')]          = urwid.CURSOR_RIGHT
urwid.command_map[Key('meta-b')]         = urwid.CURSOR_WORD_LEFT
urwid.command_map[Key('meta-f')]         = urwid.CURSOR_WORD_RIGHT

urwid.command_map[Key('home')]           = urwid.CURSOR_MAX_LEFT
urwid.command_map[Key('end')]            = urwid.CURSOR_MAX_RIGHT
urwid.command_map[Key('ctrl-a')]         = urwid.CURSOR_MAX_LEFT
urwid.command_map[Key('ctrl-e')]         = urwid.CURSOR_MAX_RIGHT

urwid.command_map[Key('ctrl-k')]         = urwid.DELETE_TO_EOL
urwid.command_map[Key('ctrl-u')]         = urwid.DELETE_LINE
urwid.command_map[Key('ctrl-d')]         = urwid.DELETE_CHAR_UNDER_CURSOR
urwid.command_map[Key('meta-d')]         = urwid.DELETE_WORD_LEFT
urwid.command_map[Key('meta-backspace')] = urwid.DELETE_WORD_RIGHT
urwid.command_map[Key('ctrl-w')]         = urwid.DELETE_WORD_RIGHT

urwid.command_map[Key('enter')]          = urwid.ACTIVATE
urwid.command_map[Key('escape')]         = urwid.CANCEL
urwid.command_map[Key('ctrl-g')]         = urwid.CANCEL
urwid.command_map[Key('ctrl-l')]         = urwid.REDRAW_SCREEN


import re
import operator
class Edit_readline(urwid.Edit):
    def keypress(self, size, key):
        def move_to_next_word(forward=True):
            if forward:
                match_iterator  = re.finditer(r'(\b\W+|$)', self.edit_text, flags=re.UNICODE)
                match_positions = (m.start() for m in match_iterator)
                op = operator.gt
            else:
                match_iterator  = re.finditer(r'(\w+\b|^)', self.edit_text, flags=re.UNICODE)
                match_positions = reversed([m.start() for m in match_iterator])
                op = operator.lt
            for pos in match_positions:
                if op(pos, self.edit_pos):
                    self.set_edit_pos(pos)
                    return pos

        cmd = self._command_map[key]
        if cmd is urwid.DELETE_TO_EOL:
            self.edit_text = self.edit_text[:self.edit_pos]
            return None
        elif cmd is urwid.DELETE_LINE:
            self.set_edit_text('')
            return None
        elif cmd is urwid.DELETE_CHAR_UNDER_CURSOR:
            return super().keypress(size, 'delete')
        elif cmd is urwid.CURSOR_WORD_RIGHT:
            move_to_next_word(forward=True)
            return None
        elif cmd is urwid.CURSOR_WORD_LEFT:
            move_to_next_word(forward=False)
            return None
        elif cmd is urwid.DELETE_WORD_LEFT:
            start_pos = self.edit_pos
            end_pos = move_to_next_word(forward=True)
            if end_pos is not None:
                self.set_edit_text(self.edit_text[:start_pos] + self.edit_text[end_pos:])
            self.edit_pos = start_pos
            return None
        elif cmd is urwid.DELETE_WORD_RIGHT:
            end_pos = self.edit_pos
            start_pos = move_to_next_word(forward=False)
            if start_pos is not None:
                self.set_edit_text(self.edit_text[:start_pos] + self.edit_text[end_pos:])
            return None
        elif key == 'space':
            return super().keypress(size, ' ')
        else:
            return super().keypress(size, key)

urwid.Edit = Edit_readline


# Limit the impact of the high CPU load bug
# https://github.com/urwid/urwid/pull/86
# https://github.com/urwid/urwid/issues/90
urwid.AsyncioEventLoop._idle_emulation_delay = 1/25


# Raise UnicodeDecodeError properly
# https://github.com/urwid/urwid/pull/92
# https://github.com/urwid/urwid/pull/196
class AsyncioEventLoop_patched(urwid.AsyncioEventLoop):
    def _exception_handler(self, loop, context):
        exc = context.get('exception')
        if exc:
            loop.stop()
            if not isinstance(exc, urwid.ExitMainLoop):
                self._exc_info = exc
        else:
            loop.default_exception_handler(context)

    def run(self):
        """
        Start the event loop.  Exit the loop when any callback raises
        an exception.  If ExitMainLoop is raised, exit cleanly.
        """
        self._loop.set_exception_handler(self._exception_handler)
        self._loop.run_forever()
        if self._exc_info:
            raise self._exc_info

urwid.AsyncioEventLoop = AsyncioEventLoop_patched


class ListBox_patched(urwid.ListBox):
    def keypress(self, size, key):
        # Offer key to focused widget first
        # https://github.com/urwid/urwid/pull/233
        focused_widget = self.focus
        if focused_widget is not None and focused_widget.selectable() and \
           focused_widget.keypress((size[0],), key) is None:
            return None

        # Add support for home/end keys
        # https://github.com/urwid/urwid/pull/229
        key = super().keypress(size, key)
        if self.focus is not None:
            if key == 'home':
                self.focus_position = next(iter(self.body.positions()))
                self.set_focus_valign('top')
                self._invalidate()
                return None
            elif key == 'end':
                self.focus_position = next(iter(self.body.positions(reverse=True)))
                self.set_focus_valign('bottom')
                self._invalidate()
                return None
        return key


    # Add support for ScrollBar class (see stig.tui.scroll)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rows_max = None

    def _invalidate(self):
        super()._invalidate()
        self._rows_max = None

    def get_scrollpos(self, size, focus=False):
        """Current scrolling position

        Lower limit is 0, upper limit is the highest index of `body`.
        """
        middle, top, bottom = self.calculate_visible(size, focus)
        if middle is None:
            return 0
        else:
            offset_rows, _, focus_pos, _, _ = middle
            maxcol, maxrow = size
            flow_size = (maxcol,)

            body = self.body
            if hasattr(body, 'positions'):
                # For body[pos], pos can be anything, not just an int.  In that
                # case, the positions() method returns an interable of valid
                # positions.
                positions = tuple(self.body.positions())
                focus_index = positions.index(focus_pos)
                widgets_above_focus = (body[pos] for pos in positions[:focus_index])
            else:
                # Treat body like a normal list
                widgets_above_focus = (w for w in body[:focus_pos])

            rows_above_focus = sum(w.rows(flow_size) for w in widgets_above_focus)
            rows_above_top = rows_above_focus - offset_rows
            return rows_above_top

    def rows_max(self, size, focus=False):
        if self._rows_max is None:
            flow_size = (size[0],)
            body = self.body
            if hasattr(body, 'positions'):
                self._rows_max = sum(body[pos].rows(flow_size) for pos in body.positions())
            else:
                self._rows_max = sum(w.rows(flow_size) for w in self.body)
        return self._rows_max

urwid.ListBox = ListBox_patched
