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

import urwid

from ..scroll import ScrollBar
from ..table import Table
from .plist_columns import TUICOLUMNS
from . import (make_ItemWidget_class, ListWidgetBase)


PeerItemWidget = make_ItemWidget_class('Peer', TUICOLUMNS, unfocused='peerlist')


class PeerListWidget(ListWidgetBase):
    TUICOLUMNS = TUICOLUMNS
    ListItemClass = PeerItemWidget
    keymap_context = 'peer'
    palette_name = 'peerlist'

    def __init__(self, srvapi, keymap, tfilter=None, pfilter=None, columns=None, sort=None, title=None):
        super().__init__(srvapi, keymap, columns=columns, sort=sort, title=title)
        self._tfilter = tfilter
        self._pfilter = pfilter

        # Create peer filter generator
        if pfilter is not None:
            def filter_peers(peers):
                yield from pfilter.apply(peers)
        else:
            def filter_peers(peers):
                yield from peers
        self._maybe_filter_peers = filter_peers

        self._poller = self._srvapi.create_poller(
            self._srvapi.torrent.torrents, tfilter, keys=('peers', 'name', 'id'))
        self._poller.on_response(self._handle_peers)

    def _handle_peers(self, response):
        if response is None or not response.torrents:
            self.clear()
        else:
            def peers_combined(torrents):
                for t in torrents:
                    yield from self._maybe_filter_peers(t['peers'])
            self._items = {p['id']:p for p in peers_combined(response.torrents)}
        self._invalidate()

    @property
    def sort(self):
        return self._sort

    @sort.setter
    def sort(self, sort):
        ListWidgetBase.sort.fset(self, sort)
        self._poller.poll()

    @property
    def title_name(self):
        if self._title is None:
            # self._tfilter is either None or a TorrentFilter instance
            title = str(self._tfilter or 'all')
            if self._pfilter:
                title += ' %s' % self._pfilter
            return title
        else:
            return ListWidgetBase.title_name.fget(self)
