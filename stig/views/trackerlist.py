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

"""TUI and CLI specs for tracker list columns"""

from ..logging import make_logger
log = make_logger(__name__)

from . import (ColumnBase, _ensure_string_without_unit)


COLUMNS = {}


class TorrentName(ColumnBase):
    header = {'left': 'Torrent'}
    align = 'left'
    width = None
    may_have_wide_chars = True

    def get_value(self):
        return self.data['tname']

COLUMNS['torrent'] = TorrentName


class Tier(ColumnBase):
    header = {'left': 'Tier'}
    align = 'right'
    width = 4

    def get_value(self):
        return self.data['tier']

COLUMNS['tier'] = Tier


class Domain(ColumnBase):
    header = {'left': 'Domain'}
    align = 'left'
    width = None

    def get_value(self):
        return self.data['domain']

COLUMNS['domain'] = Domain


class AnnounceURL(ColumnBase):
    header = {'left': 'Announce'}
    align = 'left'
    width = None

    def get_value(self):
        return self.data['url-announce']

COLUMNS['url-announce'] = AnnounceURL


class ScrapeURL(ColumnBase):
    header = {'left': 'Scrape'}
    align = 'left'
    width = None

    def get_value(self):
        return self.data['url-scrape']

COLUMNS['url-scrape'] = ScrapeURL


class State(ColumnBase):
    header = {'left': 'State'}
    align = 'right'
    width = 10

    def get_value(self):
        return self.data['state']

COLUMNS['state'] = State


class Error(ColumnBase):
    header = {'left': 'Error'}
    align = 'left'
    width = None

    def get_value(self):
        return self.data['error']

COLUMNS['error'] = Error


class Downloads(ColumnBase):
    header = {'left': 'Downloads'}
    align = 'right'
    width = 9

    def get_value(self):
        return self.data['count-downloads']

COLUMNS['downloads'] = Downloads


class Leeches(ColumnBase):
    header = {'left': 'Leeches'}
    align = 'right'
    width = 7

    def get_value(self):
        return self.data['count-leeches']

COLUMNS['leeches'] = Leeches


class Seeds(ColumnBase):
    header = {'left': 'Seeds'}
    align = 'right'
    width = 5

    def get_value(self):
        return self.data['count-seeds']

COLUMNS['seeds'] = Seeds


class LastAnnounce(ColumnBase):
    header = {'left': 'Last Announce'}
    align = 'right'
    width = 13

    def get_value(self):
        return self.data['time-last-announce']

COLUMNS['last-announce'] = LastAnnounce


class NextAnnounce(ColumnBase):
    header = {'left': 'Next Announce'}
    align = 'right'
    width = 13

    def get_value(self):
        return self.data['time-next-announce']

COLUMNS['next-announce'] = NextAnnounce


class LastScrape(ColumnBase):
    header = {'left': 'Last Scrape'}
    align = 'right'
    width = 11

    def get_value(self):
        return self.data['time-last-scrape']

COLUMNS['last-scrape'] = LastScrape


class NextScrape(ColumnBase):
    header = {'left': 'Next Scrape'}
    align = 'right'
    width = 11

    def get_value(self):
        return self.data['time-next-scrape']

COLUMNS['next-scrape'] = NextScrape