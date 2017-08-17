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

from .. import (InitCommand, ExpectedResource)
from . import _mixin as mixin
from . _common import (make_COLUMNS_doc, make_SORT_ORDERS_doc, make_SCRIPTING_doc)

import asyncio
from collections import abc


class ListTrackersCmdbase(mixin.get_tracker_sorter, mixin.get_tracker_columns,
                          mixin.get_tracker_filter, metaclass=InitCommand):
    name = 'trackerlist'
    aliases = ('trkls', 'lstrk')
    provides = set()
    category = 'tracker'
    description = 'List tracker(s) of torrent(s)'
    usage = ('trackerlist [<OPTIONS>]',
             'trackerlist [<OPTIONS>] <TORRENT FILTER>',
             'trackerlist [<OPTIONS>] <TORRENT FILTER> <TRACKER FILTER>')
    examples = ()  # TODO
    argspecs = (
        {'names': ('TORRENT FILTER',), 'nargs': '?',
         'description': 'Filter expression (see `help filter`) or focused torrent in the TUI'},

        { 'names': ('TRACKER FILTER',), 'nargs': '?',
          'description': 'Filter expression (see `help filter`)' },

        { 'names': ('--sort', '-s'),
          'default_description': "current value of 'sort.trackers' setting",
          'description': ('Comma-separated list of sort orders '
                          "(see SORT ORDERS section)") },

        { 'names': ('--columns', '-c'),
          'default_description': "current value of 'columns.trackers' setting",
          'description': ('Comma-separated list of column names '
                          "(see COLUMNS section)") },
    )
    cfg = ExpectedResource

    from ...views.trackerlist import COLUMNS
    from ...client.sorters.trksorter import TorrentTrackerSorter
    more_sections = {
        'COLUMNS': make_COLUMNS_doc(COLUMNS, '--columns', 'columns.trackers', append=(
            '',
            'The "torrent" column is added automatically if multiple '
            'torrents could be listed potentially.')),
        'SORT ORDERS': make_SORT_ORDERS_doc(TorrentTrackerSorter, '--sort', 'sort.trackers'),
        'SCRIPTING': make_SCRIPTING_doc(name),
    }

    async def run(self, TORRENT_FILTER, TRACKER_FILTER, sort, columns):
        columns = self.cfg['columns.trackers'].value if columns is None else columns
        sort = self.cfg['sort.trackers'].value if sort is None else sort
        try:
            torfilter = self.select_torrents(TORRENT_FILTER,
                                             allow_no_filter=True,
                                             discover_torrent=True)
            trkfilter = self.get_tracker_filter(TRACKER_FILTER)
            sort      = self.get_tracker_sorter(sort)
            columns   = self.get_tracker_columns(columns)
        except ValueError as e:
            log.error(e)
            return False

        # Unless we're listing trackers of exactly one torrent, specified by its
        # ID, automatically add the 'torrent' column.
        if 'torrent' not in columns and \
           (not isinstance(torfilter, abc.Sequence) or len(torfilter) != 1):
            columns.insert(0, 'torrent')

        log.debug('Listing %s trackers of %s torrents', trkfilter, torfilter)

        if asyncio.iscoroutinefunction(self.make_trklist):
            return await self.make_trklist(torfilter, trkfilter, sort, columns)
        else:
            return self.make_trklist(torfilter, trkfilter, sort, columns)


class AnnounceTorrentsCmdbase(metaclass=InitCommand):
    name = 'announce'
    aliases = ('an',)
    provides = set()
    category = 'tracker'
    description = 'Announce torrents to their trackers now if possible'
    usage = ('announce',
             'announce <TORRENT FILTER> <TORRENT FILTER> ...')
    examples = ('announce tracker~example.org',)
    argspecs = (
        { 'names': ('TORRENT FILTER',), 'nargs': '*',
          'description': 'Filter expression (see `help filter`) or focused torrent in the TUI'},
    )
    srvapi = ExpectedResource

    async def run(self, TORRENT_FILTER):
        try:
            tfilter = self.select_torrents(TORRENT_FILTER,
                                           allow_no_filter=False,
                                           discover_torrent=True)
        except ValueError as e:
            log.error(e)
            return False
        else:
            response = await self.make_request(
                self.srvapi.torrent.announce(tfilter),
                polling_frenzy=False)
            return response.success
