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

from string import hexdigits as HEXDIGITS
from collections import abc
import os
import base64
import unicodedata

from ..utils import (Response, URL)
from .torrent import (TorrentFields, Torrent)
from .. import ClientError
from ..filters.tfilter import TorrentFilter
from ..filters.ffilter import TorrentFileFilter
from .. import convert
from .. import constants as const


class _TorrentCache():
    def __init__(self, raw_torrents=()):
        self._tdict = {}  # Map torrent IDs to Torrent objects

    def update(self, raw_torrents):
        # import time ; start = time.time()
        tdict = self._tdict
        for rt in raw_torrents:
            tid = rt['id']
            if tid in tdict:
                # Update existing torrent
                # log.debug('Updating torrent #%d, %d keys: %s', tid, len(rt), tuple(rt))
                tdict[tid].update(rt)
            else:
                # Add new torrent
                # log.debug('Adding torrent #%d, %d keys: %s', tid, len(rt), tuple(rt))
                tdict[tid] = Torrent(rt)
        # log.debug('Updated %d cached with %d new torrents in %.3fms',
        #           len(tdict), len(raw_torrents), (time.time()-start)*1000)

    def purge(self, existing_tids):
        """Remove torrents with IDs that are not in `existing_ids`"""
        tdict = self._tdict
        known_tids = set(tdict)
        removed_tids = known_tids.difference(existing_tids)
        for tid in removed_tids:
            del tdict[tid]

    def get(self, *ids):
        """Return tuple of Torrent objects"""
        if ids:
            return tuple(t for tid,t in self._tdict.items() if tid in ids)
        else:
            return tuple(self._tdict.values())

    def files_initialized(self, ids):
        """Wether all cached Torrents have a 'files' key"""
        return all('files' in t
                   for t in self._tdict.values()
                   if t['id'] in ids)

    def __len__(self):
        return len(self._tdict)

    def __repr__(self):
        tlist = ', '.join('#'+str(tid) for tid in self._tdict)
        return '<{cls} {tlist}>'.format(cls=type(self).__name__,
                                        tlist=tlist or '(empty)')


class TorrentAPI():
    """High-level abstraction of the Transmission RPC protocol"""

    def __init__(self, rpc):
        self.rpc = rpc
        self._tcache = _TorrentCache()

    async def _request(self, method, *args, **kwargs):
        try:
            result = await method(*args, **kwargs)
        except ClientError as e:
            return Response(result=None, msgs=(e,), success=False)
        else:
            return Response(result=result, msgs=(), success=True)

    async def _abs_download_path(self, path, autoconnect=True):
        """Turn relative `path` into absolute path based on default download path"""
        if not autoconnect and not self.rpc.connected:
            return None
        elif not os.path.isabs(path):
            response = await self._request(self.rpc.session_get)
            if not response.success:
                return Response(path=None, success=False, msgs=response.msgs)
            else:
                download_dir = response.result['download-dir']
                abs_path = os.path.normpath(os.path.join(download_dir, path))
                return Response(path=abs_path, success=True)
        return Response(path=path, success=True)

    async def add(self, torrent, stopped=False, path=None):
        """Add torrent from file, URL or hash

        torrent: Path to local file, web/magnet link or hash
        stopped: False to start downloading immediately, True otherise
        path:    Download directory or `None` for default directory

        Return Response with the following properties:
            torrent: Torrent object with the keys 'id' and 'name' if the
                     torrent could be added or if it already exists, otherwise
                     None
            success: False if torrent could not be added or already exists,
                     True otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        torrent_str = torrent
        torrent = None
        msgs = []
        success = False

        args = {'paused': bool(stopped)}
        if path is not None:
            response = await self._abs_download_path(path)
            if not response.success:
                return Response(success=False, torrent=None, msgs=response.msgs)
            else:
                args['download-dir'] = response.path

        # Check if torrent_str is path to local torrent file
        torrent_str_path = os.path.expanduser(torrent_str)
        if os.path.exists(torrent_str_path):
            torrent_str = torrent_str_path
            del torrent_str_path

            # Read local file
            try:
                with open(torrent_str, 'rb') as f:
                    args['metainfo'] = str(base64.b64encode(f.read()),
                                           encoding='ascii')
            except OSError as e:
                msgs.append(ClientError('%s: %s' % (e.strerror, torrent_str)))
                return Response(success=success, torrent=torrent, msgs=msgs)
        elif len(torrent_str) == 40 and all(c in HEXDIGITS for c in torrent_str):
            # Convert hash to magnet link
            args['filename'] = 'magnet:?xt=urn:btih:' + torrent_str
        else:
            # It's probably a link, let the daemon figure it out
            args['filename'] = torrent_str

        response = await self._request(self.rpc.torrent_add, **args)
        if not response.success:
            if 'Invalid or corrupt' in str(response.msgs[0]):
                msgs = (ClientError('Invalid or corrupt torrent: {!r}'.format(torrent_str)),)
            else:
                msgs = response.msgs
            return Response(success=False, torrent=None, msgs=msgs)
        else:
            result = response.result
            if 'torrent-duplicate' in result:
                info = result['torrent-duplicate']
                msgs.append(ClientError('Torrent already exists: ' + info['name']))
                success = False
            elif 'torrent-added' in result:
                info = result['torrent-added']
                msgs.append('Added %s' % info['name'])
                success = True
            else:
                raise RuntimeError('Malformed response: {}'.format(result))
            torrent = Torrent({'id': info['id'], 'name': info['name']})

        return Response(success=success, torrent=torrent, msgs=msgs)


    async def _request_torrents(self, fields, ids=None):
        """Unmodified 'torrent-get' request"""
        try:
            if 'id' not in fields:
                fields = ('id',) + tuple(fields)
            if ids is None:
                # Request all IDs
                raw_tlist = await self.rpc.torrent_get(fields=fields)
            else:
                if len(ids) > 0:
                    # Request given IDs
                    raw_tlist = await self.rpc.torrent_get(fields=fields, ids=ids)
                else:
                    # No IDs (i.e. empty torrent list) requested
                    raw_tlist = []
        except ClientError as e:
            return Response(success=False, raw_torrents=[], msgs=[e])
        else:
            self._tcache.update(raw_tlist)
            return Response(success=True, raw_torrents=raw_tlist)

    async def _get_torrents_by_ids(self, keys, ids=None, autoconnect=True):
        """Return a Response object with 'torrents' set to a tuple of Torrents

        keys: 'ALL' for all supported Torrent keys or a sequence of key
              strings (see client.ttypes.TYPES for available keys)
        ids: None for all torrents or a sequence of wanted IDs
        autoconnect: Wether to attempt to connect automatically if not
                     connected; if False and not connected, return None
        """
        if not autoconnect and not self.rpc.connected:
            return None
        elif keys == 'ALL':
            fields = TorrentFields(keys)
        else:
            fields = TorrentFields(*keys)

        # The 'files' RPC field only returns static information while variable
        # information is in 'filestats'. Since all Torrent values are cached
        # anyway, we only have to request 'files' once if 'fileStats' is
        # requested.
        if 'fileStats' in fields and not self._tcache.files_initialized(ids):
            log.debug('Initializing files for torrents: %s', ids)
            response = await self._request_torrents(('files',), ids)
            if not response.success:
                return Response(success=False, torrents=(), msgs=response.msgs)

        tlist = ()
        msgs = []
        success = False

        response = await self._request_torrents(fields, ids)
        if not response.success:
            return Response(success=False, torrents=(), msgs=response.msgs)
        else:
            from time import time
            start = time()

            raw_tlist = response.raw_torrents
            if ids:
                tlist = self._tcache.get(*ids)
                for tid in ids:
                    # Torrent objects are equal to an integer of the torrent's ID
                    if tid not in tlist:
                        msgs.append(ClientError('No torrent with ID: {}'.format(tid)))
            else:
                self._tcache.purge(t['id'] for t in raw_tlist)  # Remove deleted torrents from cache
                tlist = self._tcache.get()
            success = len(tlist) > 0 or not ids

            log.debug('Found %d torrents in %.3fms', len(tlist), (time()-start)*1e3)

        return Response(success=success, torrents=tlist, msgs=msgs)

    async def _get_torrents_by_filter(self, keys, tfilter=None, autoconnect=True):
        """Return a Response object with 'torrents' set to a tuple of Torrents

        keys: See _get_torrents_by_ids
        tfilter: A TorrentFilter instance or None
        autoconnect: See _get_torrents_by_ids
        """
        if not autoconnect and not self.rpc.connected:
            return None
        elif tfilter == None:
            log.debug('Looking for all torrents with keys: %s', keys)
            # No filter specified - just return all torrents with the specified keys
            return await self._get_torrents_by_ids(keys=keys)
        else:
            log.debug('Looking for %s torrents with keys: %s', tfilter, keys)
            tlist = ()
            msgs = []
            success = False
            if isinstance(tfilter, str):
                tfilter = TorrentFilter(tfilter)

            # Request all torrents with the keys needed to filter them
            log.debug('Requesting full list with filter keys: %s', tfilter.needed_keys)
            response = await self._get_torrents_by_ids(keys=tfilter.needed_keys)
            if response.success:
                # Find IDs of torrents that match tfilter
                wanted_ids = tuple(t['id'] for t in tfilter.apply(response.torrents))
                log.debug('Wanted IDs: %s', wanted_ids)
                if len(wanted_ids) > 0:
                    # Get only wanted torrents with all wanted keys
                    try:
                        response = await self._get_torrents_by_ids(keys, wanted_ids)
                    except ClientError as e:
                        msgs.append(ClientError(str(e)))
                    else:
                        tlist = tuple(response.torrents)
            else:
                msgs.extend(response.msgs)

            success = len(tlist) > 0
            if not success:
                msgs.append(ClientError('No matching torrents: {}'.format(tfilter)))
            else:
                msgs.append('Found {} {} torrent{}'.format(
                    len(tlist), tfilter, '' if len(tlist) == 1 else 's'))

            return Response(success=success, torrents=tlist, msgs=msgs)

    async def torrents(self, torrents=None, keys='ALL', autoconnect=True):
        """Fetch and return torrents

        torrents: Iterator of torrent IDs, TorrentFilter object (or its string
                  representation) or None for all torrents
        keys: tuple of Torrent keys to fetch or 'ALL' for all torrents
        autoconnect: Wether to attempt to connect automatically if not
                     connected; if False and not connected, return None

        Return Response with the following properties:
            torrents: tuple of Torrent objects with requested torrents
            success: False if no torrents were found, True otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if not autoconnect and not self.rpc.connected:
            return None
        elif torrents is None:
            return await self._get_torrents_by_ids(keys)
        elif isinstance(torrents, (str, TorrentFilter)):
            return await self._get_torrents_by_filter(keys, tfilter=torrents)
        elif isinstance(torrents, abc.Sequence) and \
             all(isinstance(id, int) for id in torrents):
            return await self._get_torrents_by_ids(keys, ids=torrents)
        else:
            raise ValueError("Invalid 'torrents' argument: {!r}".format(torrents))

    async def _torrent_action(self, method, torrents=None, method_args={}, check=None,
                              keys_check=(), keys_return=(), autoconnect=True):
        """Helper method that operates on torrents (start, stop, remove, etc)

        method: Any method from TransmissionRPC that accepts torrent ids
        torrents: See `torrents` method
        method_args: Dictionary with keyword arguments for method (except 'ids')
        check: None or callable that is called with every torrent; must return
               a 2-tuple of (SUCCESS, MESSAGE) where SUCCESS is evaluated as
               bool and MESSAGE a string or None.  If SUCCESS evaluates to
               True, `method` is applied to the torrent, otherwise not.
        keys_check: List of Torrent keys the check function needs ('id' and
                    'name' are always included)
        keys_return: List of Torrent keys of returned torrents ('id' and 'name'
                    are always included)
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that `method` was applied to with the
                      keys 'id' and 'name'
            success: True if `method` was successfully applied to at least one
                     torrent, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if not autoconnect and not self.rpc.connected:
            return None

        tlist = []
        msgs = []
        success = False

        # Always provide some keys
        keys_check = set(tuple(keys_check) + ('id', 'name'))
        keys_return = set(tuple(keys_return) + ('id', 'name'))

        response = await self.torrents(torrents, keys=keys_check)
        if not response.success:
            return Response(success=False, torrents=(), msgs=response.msgs)
        else:
            msgs = list(response.msgs)

        if check is None:
            tlist = response.torrents
        else:
            # Filter torrents through check function
            for t in response.torrents:
                passed, msg = check(t)
                if passed:
                    tlist.append(t)
                    if msg is not None:
                        msgs.append(msg)
                else:
                    if msg is not None:
                        msgs.append(ClientError(msg))

        # Apply method to torrents that passed the check function
        if len(tlist) > 0:
            try:
                # Ignore response because it is always {}, except for
                # 'torrent-get' requests, which this method is not meant for.
                await method(ids=tuple(t['id'] for t in tlist), **method_args)
            except ClientError as e:
                msgs.append(e)
                tlist = ()

        # Get the requested keys for returned torrents
        if len(tlist) > 0:
            response = await self._get_torrents_by_ids(keys_return, tuple(t['id'] for t in tlist))
            if not response.success:
                return Response(success=False, torrents=(), msgs=response.msgs)
            return Response(success=True, torrents=response.torrents, msgs=msgs)
        else:
            return Response(success=False, torrents=(), msgs=msgs)

    async def stop(self, torrents, autoconnect=True):
        """Stop down-/uploading torrents

        torrents: See `torrents` method
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that were stopped with the keys 'id'
                      and 'name'
            success: True if any torrents were found and stopped, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        def check(t):
            if t['status'].STOPPED in t['status']:
                return (False, 'Already stopped: ' + t['name'])
            else:
                return (True, 'Stopping ' + t['name'])

        return await self._torrent_action(self.rpc.torrent_stop, torrents,
                                          check=check, keys_check=('status',),
                                          autoconnect=autoconnect)

    async def start(self, torrents, force=False, autoconnect=True):
        """Start down-/uploading torrents

        torrents: See `torrents` method
        force: Start downloading even if download queue is active and full
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that were started with the keys 'id'
                      and 'name'
            success: True if any torrents were found and started, False
                     otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        def check(t):
            if t['status'].STOPPED in t['status']:
                return (True, 'Starting ' + t['name'])
            else:
                return (False, 'Already started: ' + t['name'])

        if force:
            method = self.rpc.torrent_start_now
        else:
            method = self.rpc.torrent_start

        return await self._torrent_action(method, torrents,
                                          check=check, keys_check=('status',),
                                          method_args={'force':force},
                                          autoconnect=autoconnect)

    async def toggle_stopped(self, torrents, force=False, autoconnect=True):
        """Start down-/uploading torrents

        torrents: See `torrents` method
        force: See `start` method
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that were toggled with the keys 'id'
                      and 'name'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        response = await self.torrents(torrents, keys=('status',))
        if not response.success:
            return Response(success=False, torrents=(), msgs=response.msgs)

        stopped, running = [], []
        for t in response.torrents:
            if t['status'].STOPPED in t['status']:
                stopped.append(t)
            else:
                running.append(t)

        torrents, msgs = ((), [])
        if len(running) > 0:
            r = await self.stop(tuple(t['id'] for t in running))
            torrents += r.torrents
            msgs += r.msgs
        if len(stopped) > 0:
            r = await self.start(tuple(t['id'] for t in stopped), force=force)
            torrents += r.torrents
            msgs += r.msgs

        return Response(torrents=torrents,
                        success=len(torrents) > 0,
                        msgs=msgs)

    async def verify(self, torrents, autoconnect=True):
        """Verify torrents's downloaded data

        torrents: See `torrents` method
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that will be verified with the keys
                      'id' and 'name'
            success: True if any torrents were found and will be verified,
                     False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        def check(t):
            if t['status'].VERIFY in t['status']:
                if t['status'].QUEUED in t['status']:
                    return (False, 'Already queued for verification: ' + t['name'])
                else:
                    return (False, 'Already verifying: ' + t['name'])
            else:
                return (True, 'Verifying ' + t['name'])

        return await self._torrent_action(self.rpc.torrent_verify, torrents,
                                          check=check, keys_check=('status',),
                                          autoconnect=autoconnect)

    async def remove(self, torrents, delete=False, autoconnect=True):
        """Remove torrents

        torrents: See `torrents` method
        delete: True if downloaded files should be deleted
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that were removed with the keys 'id'
                      and 'name'
            success: True if any torrents were found and removed, False
                     otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if delete:
            msg = 'Deleting %s (including files)'
        else:
            msg = 'Removing %s (keeping files)'

        def create_info_msg(t):
            return (True, msg % t['name'])

        return await self._torrent_action(self.rpc.torrent_remove, torrents,
                                          check=create_info_msg,
                                          method_args={'delete-local-data': delete},
                                          autoconnect=autoconnect)


    async def move(self, torrents, path, autoconnect=True):
        """Change torrents' location in the file system

        torrents: See `torrents` method
        path: Destination of the specified torrents; relative paths are relative
              to the default download path.
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents that were removed with the keys 'id',
                      'name' and 'path' (after the move)
            success: True if any torrents were found and had matching files,
                     False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if not autoconnect and not self.rpc.connected:
            return None

        # Transmission wants an absolute path
        response = await self._abs_download_path(path)
        if not response.success:
            return Response(torrents=(), success=False, msgs=response.msgs)
        else:
            path = response.path

        def create_info_msg(t):
            if t['path'] != path:
                return (True, 'Moved to %s: %s' % (path, t['name']))
            else:
                return (False, 'Already in %s: %s' % (path, t['name']))

        return await self._torrent_action(self.rpc.torrent_set_location, torrents,
                                          check=create_info_msg, keys_check=('path',),
                                          keys_return=('path',),
                                          method_args={'move': True, 'location': path})


    async def file_priority(self, torrents, priority, files, autoconnect=True):
        """Change download priority of individual torrent files

        torrents: See `torrents` method
        priority: 'high', 'low', 'normal' or 'shun'
        files: TorrentFileFilter object (or its string representation), sequence
               of (torrent ID, file ID) tuples or None for all files
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of matching Torrents that have matching files with
                      the keys 'id', 'name' and 'files'
            success: True if any torrents were found and had matching files,
                     False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if not autoconnect and not self.rpc.connected:
            return None

        response = await self.torrents(torrents, keys=('name', 'files'))
        if not response.success:
            return Response(torrents=(), success=False, msgs=response.msgs)
        else:
            torrents = ()
            torrent_ids = []
            msgs = []
            success = False

            if isinstance(files, str):
                files = TorrentFileFilter(files)

            # Set filter_files to a function that takes a TorrentFileTree and
            # returns a list of TorrentFiles.
            if files is None:
                filter_files = lambda ftree: tuple(ftree.files)
            elif isinstance(files, TorrentFileFilter):
                filter_files = lambda ftree: tuple(files.apply(ftree.files))
            elif isinstance(files, abc.Sequence) and \
                 all(isinstance(tid, int) and isinstance(fid, int) for tid,fid in files):
                filter_files = lambda ftree: tuple(f for f in ftree.files
                                                   if (f['tid'],f['id']) in files)
            else:
                raise ValueError("Invalid 'files' argument: {!r}".format(files))

            for t in sorted(response.torrents, key=lambda t: t['name'].lower()):
                # Filter torrent's files
                flist = filter_files(t['files'])
                if files is None:
                    msgs.append('{} file{}: {}'
                                .format(len(flist), '' if len(flist) == 1 else 's', t['name']))
                else:
                    if not flist:
                        msgs.append(ClientError('No matching files: {}'.format(t['name'])))
                    else:
                        msgs.append('{} matching file{}: {}'
                                    .format(len(flist), '' if len(flist) == 1 else 's', t['name']))
                success = len(flist) > 0 or success

                # Transmission wants a list of file indexes; luckily, the
                # file's ID is its index (see .torrent.TorrentFileTree).
                findexes = tuple(f['id'] for f in flist)
                if findexes:
                    response = await self._set_files_priority(priority, t['id'], findexes)
                    if response.success:
                        torrent_ids.append(t['id'])
                    msgs.extend(response.msgs)

        if torrent_ids:
            response = await self.torrents(torrent_ids, keys=('name', 'files'))
            if response.success:
                torrents = response.torrents
        return Response(torrents=torrents,
                        success=success,
                        msgs=msgs)

    async def _set_files_priority(self, priority, torrent_id, file_indexes, autoconnect):
        fi = tuple(file_indexes)
        if priority in ('high', 'normal', 'low'):
            return await self._torrent_action(
                self.rpc.torrent_set, (torrent_id,),
                method_args={'priority-%s' % priority: fi, 'files-wanted': fi},
                autoconnect=autoconnect)
        elif priority == 'shun':
            return await self._torrent_action(
                self.rpc.torrent_set, (torrent_id,),
                method_args={'files-unwanted': fi},
                autoconnect=autoconnect)
        else:
            raise ValueError('Invalid priority: {!r}'.format(priority))


    async def _limit_rate(self, direction, torrents, rate, autoconnect=True):
        if not autoconnect and not self.rpc.connected:
            return None

        # Make number or constant from `rate`
        if rate is None:
            limit = const.UNLIMITED
        else:
            r = convert.bandwidth.from_string(rate, unit='byte')
            limit = const.UNLIMITED if r <= 0 else r

        # Create 'torrent_set' arguments
        if limit is const.UNLIMITED:
            args = {'%sloadLimited' % direction: False}
        else:
            l = limit / 8 if limit.unit == 'b' else limit
            args = {'%sloadLimited' % direction: True,
                    '%sloadLimit' % direction: int(l/1000)}  # Transmission expects kilobytes

        response = await self._torrent_action(self.rpc.torrent_set, torrents,
                                              method_args=args)

        if not response.success:
            return response
        else:
            def create_info_msg(t):
                limit = t['rate-limit-'+direction]
                limit_str = str(limit) if const.is_constant(limit) else limit.with_unit
                return 'Limited %sload rate of %s: %s' % (direction, t['name'], limit_str)

            # Fetch new list with the actual rate limits
            tids = tuple(t['id'] for t in response.torrents)
            response = await self.torrents(tids, keys=('name', 'id', 'rate-limit-'+direction))
            return Response(torrents=response.torrents,
                            success=response.success,
                            msgs=(create_info_msg(t) for t in response.torrents))

    async def limit_rate_up(self, torrents, rate, autoconnect=True):
        """Limit upload rate for individual torrent(s)

        torrents: See `torrents` method
        rate: Maximum allowed upload rate for `torrents` or `None` for default limit
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents with the keys 'id', 'name' and 'rate-limit-up'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        return await self._limit_rate('up', torrents, rate, autoconnect)

    async def limit_rate_down(self, torrents, rate, autoconnect=True):
        """Limit download rate for individual torrent(s)

        torrents: See `torrents` method
        rate: Maximum allowed download rate for `torrents` or `None` for default limit
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents with the keys 'id', 'name' and 'rate-limit-down'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        return await self._limit_rate('down', torrents, rate, autoconnect)


    async def tracker_add(self, torrents, urls, autoconnect=True):
        """Add tracker(s) to torrents

        torrents: See `torrents` method
        urls: Iterable of announce URLs
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents with the keys 'id', 'name' and 'trackers'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        if not autoconnect and not self.rpc.connected:
            return None

        # Transmission returns 'Invalid argument' if we try to add an existing
        # tracker, so first we check if any of our URLs already exist.
        response = await self.torrents(torrents, keys=('id', 'name', 'trackers',))
        if not response.success:
            return Response(success=False, torrents=(), msgs=response.msgs)
        else:
            tordict = {tor['id']:tor for tor in  response.torrents}

        # Map torrent IDs to currently used URLs by that torrent
        old_url_dict = {torid:tuple(trk['url-announce'] for trk in torrent['trackers'])
                        for torid,torrent in tordict.items()}

        # Make sure URLs are comparable
        new_urls = [URL(url) for url in urls]

        # For each torrent, report any supplied URLs that are already used
        msgs = []
        for torid,old_urls in old_url_dict.items():
            for old_url in old_urls:
                if old_url in new_urls:
                    msgs.append(ClientError('%s: Tracker already exists: %s' %
                                            (tordict[torid]['name'], old_url)))
                    new_urls.remove(old_url)

        # No URLs left to add?
        if not new_urls:
            return Response(success=False, torrents=(), msgs=msgs)

        for new_url in new_urls:
            msgs.append('%s: Adding tracker: %s' % (tordict[torid]['name'], new_url))

        # Add trackers
        args = {'trackerAdd': [str(url) for url in new_urls]}
        response = await self._torrent_action(self.rpc.torrent_set, torrents,
                                              method_args=args)
        if not response.success:
            return Response(success=False, torrents=(), msgs=msgs + list(response.msgs))
        else:
            return Response(success=True, torrents=response.torrents, msgs=msgs)

    async def tracker_remove(self, torrents, urls, partial_match=False, autoconnect=True):
        """Remove tracker(s) from torrents

        torrents: See `torrents` method
        urls: Iterable of announce URLs
        partial_match: True if given URLs match existing URLs partially
                       (e.g. 'example.org' matches 'http://tracker.example.org/')
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents with the keys 'id', 'name' and 'trackers'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request

        """
        if not autoconnect and not self.rpc.connected:
            return None

        # Get wanted torrent IDs
        response = await self.torrents(torrents, keys=('id',))
        if not response.success:
            return Response(success=False, torrents=(), msgs=response.msgs)
        else:
            torids = tuple(t['id'] for t in response.torrents)

        # Get raw tracker lists for the unaltered tracker IDs.  We need them
        # later to specify which trackers to remove.
        response = await self._request(self.rpc.torrent_get, ids=torids,
                                       fields=('id', 'name', 'trackers'))
        if not response.success or len(response.result) <= 0:
            return Response(success=False, torrents=(), msgs=response.msgs)
        else:
            raw_tor_dict = {raw_tor['id']:raw_tor for raw_tor in response.result}

        # Map torrent IDs to lists of IDs of matching trackers
        msgs = []
        remove_urls = urls
        matching_urls = []
        remove_ids = {}
        for torid,raw_tor in raw_tor_dict.items():
            remove_ids[torid] = []
            for raw_trk in raw_tor['trackers']:
                existing_url = raw_trk['announce']
                for remove_url in remove_urls:
                    if remove_url == existing_url or partial_match and remove_url in existing_url:
                        remove_ids[torid].append(raw_trk['id'])
                        matching_urls.append(remove_url)
                        msgs.append('%s: Removing tracker: %s' % (raw_tor['name'], existing_url))

            if len(remove_ids[torid]) <= 0:
                # No matching trackers for this torrent
                del remove_ids[torid]

        # Report error if no matching trackers were found for a given URL
        for mismatch in set(remove_urls).difference(matching_urls):
            msgs.append(ClientError('No matching trackers found: %r' % mismatch))

        # Finally remove trackers from torrents
        if remove_ids:
            for torid,trkids in remove_ids.items():
                response = await self._torrent_action(self.rpc.torrent_set, (torid,),
                                                      method_args={'trackerRemove': trkids})
                if not response.success:
                    return Response(success=False, torrents=(), msgs=response.msgs)

        # Get new torrent list with newly added trackers
        response = await self.torrents(tuple(remove_ids), keys=('id', 'name', 'trackers'))
        if not response.success:
            return Response(success=False, torrents=(), msgs=msgs + list(response.msgs))
        else:
            return Response(success=True, torrents=response.torrents, msgs=msgs)

    async def announce(self, torrents, autoconnect=True):
        """Announce torrents' to its tracker(s)

        torrents: See `torrents` method
        autoconnect: See `torrents` method

        Return Response with the following properties:
            torrents: tuple of Torrents with the keys 'id', 'name' and 'trackers'
            success: True if any torrents were found, False otherwise
            msgs: list of strings/`ClientError`s caused by the request
        """
        import time
        def check(t):
            if len(t['trackers']) < 1:
                return (False, 'Torrent has no trackers: %s' % t['name'])
            elif t['status'].STOPPED in t['status']:
                return (False, 'Not announcing inactive torrent: %s' % t['name'])
            elif t['time-manual-announce-allowed'] > time.time():
                return (False, ('Not allowing manual announce until %s (in %s): %r' %
                                (t['time-manual-announce-allowed'],
                                 t['time-manual-announce-allowed'].delta, t['name'])))
            else:
                return (True, 'Announcing: %s' % t['name'])

        return await self._torrent_action(self.rpc.torrent_reannounce, torrents,
                                          check=check, keys_check=('status', 'trackers',
                                                                   'time-manual-announce-allowed'),
                                          keys_return=('trackers',),
                                          autoconnect=autoconnect)
