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

from ...logging import make_logger
log = make_logger(__name__)

import urwid

from .. import main as tui

from ..table import Table
from .tlist_columns import TUICOLUMNS

COLUMNS_FOCUS_MAP = {}
for col in TUICOLUMNS.values():
    COLUMNS_FOCUS_MAP.update(col.style.focus_map)


class TorrentListItemWidget(urwid.WidgetWrap):
    def __init__(self, torrent, cells):
        self._torrent = torrent
        self._tid = torrent['id']
        self._cells = cells
        self.update(torrent)
        row = urwid.AttrMap(urwid.AttrMap(cells, attr_map=None, focus_map=COLUMNS_FOCUS_MAP),
                            'torrentlist', 'torrentlist.focused')
        super().__init__(row)

    def update(self, torrent):
        for widget in self._cells.widgets:
            widget.update(torrent)
        self._torrent = torrent

    @property
    def tid(self):
        return self._tid

    @property
    def torrent(self):
        return self._torrent

    @property
    def is_marked(self):
        return self._cells.marked.is_marked

    @is_marked.setter
    def is_marked(self, is_marked):
        self._cells.marked.is_marked = bool(is_marked)


class TorrentListWidget(urwid.WidgetWrap):
    def __init__(self, sort=None, tfilter=None, columns=[]):
        self._sort = sort
        self._tfilter = tfilter
        self._columns = columns
        self.title_updater = None

        self._table = Table(**TUICOLUMNS)
        self._table.columns = columns

        self._torrents = ()
        self._walker = urwid.SimpleFocusListWalker([])
        self._listbox = urwid.ListBox(self._walker)
        self._marked = set()

        pile = urwid.Pile([
            ('pack', urwid.AttrMap(self._table.headers, 'torrentlist.header')),
            self._listbox
        ])
        super().__init__(urwid.AttrMap(pile, 'torrentlist'))

        self._register_request()

    def _register_request(self):
        # Get keys needed for sort order, tfilter and columns
        keys = []
        if self._sort is not None:
            keys.extend(self._sort.needed_keys)
        if self._tfilter is not None:
            keys.extend(self._tfilter.needed_keys)
        for colname in self._columns:
            keys.extend(TUICOLUMNS[colname].needed_keys)

        # Register new request in request pool
        log.debug('Registering keys for %s: %s', self.id, keys)
        tui.srvapi.treqpool.register(self.id, self._handle_tlist,
                                     keys=keys,
                                     tfilter=self._tfilter)
        tui.srvapi.treqpool.poll()

    def _handle_tlist(self, torrents):
        self._torrents = tuple(torrents)
        if self.title_updater is not None:
            self.title_updater(self.title)
        self._invalidate()

    def render(self, size, focus=False):
        if self._torrents is not None:
            self._update_listitems()
            self._torrents = None
        return super().render(size, focus)

    def _update_listitems(self):
        # Remember focused torrent
        focused_torrent = self.focused_torrent

        walker = self._walker
        tdict = {t['id']:t for t in self._torrents}
        dead_tws = []
        for tw in walker:  # tw = TorrentListItemWidget
            tid = tw.tid
            try:
                # Update existing torrent widget with new data
                tw.update(tdict[tid])
                del tdict[tid]
            except KeyError:
                # Torrent has been removed
                dead_tws.append(tw)

        # Remove list items that don't exist in self._torrents anymore
        for tw in dead_tws:
            walker.remove(tw)

        # Any torrents that haven't been used to update an existing torrent are new
        if tdict:
            widgetcls = tui.keymap.wrap(TorrentListItemWidget, context='torrent')
            for tid in tdict:
                self._table.register(tid)
                row = self._table.get_row(tid)
                walker.append(widgetcls(tdict[tid], row))

        # Sort torrents
        if self._sort is not None:
            self._sort.apply(walker,
                            item_getter=lambda tw: tw.torrent,
                            inplace=True)

        # If necessary, re-focus previously focused torrent
        if focused_torrent is not None and self.focused_torrent is not None and \
           focused_torrent.tid != self.focused_torrent.tid:
            focused_tid = focused_torrent.tid
            for i,tw in enumerate(walker):
                if tw.tid == focused_tid:
                    self._listbox.focus_position = i
                    break

    def clear(self):
        """Remove all list items"""
        for tw in tuple(self._walker):
            tw.torrent.clearcache()
            self._walker.remove(tw)
        tui.srvapi.treqpool.poll()

    def update(self):
        """Call `clear` and then poll immediately"""
        self.clear()
        tui.srvapi.treqpool.poll()

    def set(self, columns=None, tfilter=None, sort=None):
        update_request = False
        old_id = self.id
        if columns is not None:
            self._table.columns = columns
            update_request = True
        if tfilter is not None:
            self._tfilter = tfilter
            update_request = True
        if sort is not None:
            self._sort = sort
            update_request = True
        if update_request:
            tui.srvapi.treqpool.remove(old_id)
            self._register_request()

    @property
    def title(self):
        title = [str(self._tfilter) if self._tfilter is not None else 'all']
        sortstr = str(self._sort)
        if sortstr is not self._sort.DEFAULT_SORT:
            title.append('{%s}' % sortstr)

        # If this method was called before rendering, the contents of the
        # listbox widget are inaccurate and we have to use self._torrents.
        # But if we're called after rendering, self._torrents is reset to
        # None.
        if self._torrents is not None:
            title.append('[%d]' % len(self._torrents))
        else:
            title.append('[%d]' % len(self._listbox.body))

        return ' '.join(title)

    @property
    def id(self):
        return 'tlist%s:%s' % (id(self), self.title)

    @property
    def focused_torrent(self):
        return self._listbox.focus

    @property
    def focus_position(self):
        return self._listbox.focus_position

    @focus_position.setter
    def focus_position(self, focus_position):
        self._listbox.focus_position = min(focus_position, len(self._listbox.body)-1)

    def mark(self, toggle=False, all=False):
        """Mark the currently focused item or all items"""
        self._set_mark(True, toggle=toggle, all=all)

    def unmark(self, toggle=False, all=False):
        """Unmark the currently focused item or all items"""
        self._set_mark(False, toggle=toggle, all=all)

    def _set_mark(self, mark, toggle=False, all=False):
        if toggle and self.focused_torrent is not None:
            mark = not self.focused_torrent.is_marked

        for widget in self._select_items_for_marking(all):
            widget.is_marked = mark
            if mark:
                self._marked.add(widget)
            else:
                self._marked.discard(widget)

    def _select_items_for_marking(self, all):
        if self.focused_torrent is not None:
            if all:
                yield from self._listbox.body
            else:
                yield self.focused_torrent
