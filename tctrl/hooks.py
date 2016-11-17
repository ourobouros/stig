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

"""General hooks that are always needed regardless of the interface"""

from .logging import make_logger
log = make_logger(__name__)

from .main import (cfg, srvapi)
from .columns.tlist import COLUMNS


def _set_rpc_timeout(timeout):
    srvapi.rpc.timeout = timeout.value
cfg['srv.timeout'].on_change(_set_rpc_timeout)


def _set_rpc_url(url):
    srvapi.url = url.value
cfg['srv.url'].on_change(_set_rpc_url)


def _set_bandwidth_unit(unit):
    srvapi.bandwidth_unit = unit.value
    u = {'bit': 'b', 'byte': 'B'}[unit.value]
    COLUMNS['rate-up'].set_unit(u)
    COLUMNS['rate-down'].set_unit(u)
cfg['unit.bandwidth'].on_change(_set_bandwidth_unit)
_set_bandwidth_unit(cfg['unit.size'])  # Initialize COLUMNS


def _set_bandwidth_prefix(prefix):
    srvapi.bandwidth_prefix = prefix.value
cfg['unitprefix.bandwidth'].on_change(_set_bandwidth_prefix)


def _set_size_unit(unit):
    srvapi.size_unit = unit.value
    u = {'bit': 'b', 'byte': 'B'}[unit.value]
    COLUMNS['size'].set_unit(u)
    COLUMNS['downloaded'].set_unit(u)
    COLUMNS['uploaded'].set_unit(u)
cfg['unit.size'].on_change(_set_size_unit)
_set_size_unit(cfg['unit.size'])  # Initialize COLUMNS


def _set_size_prefix(prefix):
    srvapi.size_prefix = prefix.value
cfg['unitprefix.size'].on_change(_set_size_prefix)
