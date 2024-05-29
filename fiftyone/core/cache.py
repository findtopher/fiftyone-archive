"""
Remote media caching.

| Copyright 2017-2023, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
import time
from datetime import datetime, timedelta
import logging
import multiprocessing
import multiprocessing.dummy
import os
import urllib.parse as urlparse

import aiofiles
import aiohttp
import backoff
import yarl

import eta.core.utils as etau

import fiftyone as fo
from fiftyone.core.service import MediaCacheService
from fiftyone.core.config import HTTPRetryConfig
import fiftyone.core.storage as fos
import fiftyone.core.utils as fou

fom = fou.lazy_import("fiftyone.core.metadata")


logger = logging.getLogger(__name__)

media_cache = None
gc_service = None


def init_media_cache(config):
    """Initializes the media cache.

    Args:
        config: a :class:`fiftyone.core.config.MediaCacheConfig`
    """
    global media_cache
    global gc_service

    media_cache = MediaCache(config)

    if media_cache.cache_size >= 0:
        gc_service = MediaCacheService()


class MediaCache(object):
    """A cache that automatically manages the downloading of remote media files
    stored in S3, GCS, or web URLs.

    Args:
        config: a :class:`fiftyone.core.config.MediaCacheConfig`
    """

    def __init__(self, config):
        self.config = config

    @property
    def cache_dir(self):
        return self.config.cache_dir

    @property
    def media_dir(self):
        return os.path.join(self.config.cache_dir, "media")

    @property
    def log_path(self):
        return os.path.join(self.config.cache_dir, "log", "gc.log")

    @property
    def _lock_path(self):
        return os.path.join(self.config.cache_dir, "lock")

    @property
    def cache_size(self):
        return self.config.cache_size_bytes

    @property
    def num_workers(self):
        return self.config.num_workers

    def stats(self, filepaths=None):
        """Returns a dictionary of stats about the cache.

        Args:
            filepaths (None): an iterable of filepaths to restrict the stats to

        Returns:
            a stats dict
        """
        current_count, current_size = _compute_cache_stats(
            self, filepaths=filepaths
        )

        cache_dir = self.cache_dir
        if self.cache_size < 0:
            cache_size = float("inf")
            cache_size_str = "unlimited"
        else:
            cache_size = self.cache_size
            cache_size_str = etau.to_human_bytes_str(cache_size)

        current_size_str = etau.to_human_bytes_str(current_size)
        load_factor = current_size / cache_size

        return {
            "cache_dir": cache_dir,
            "cache_size": cache_size,
            "cache_size_str": cache_size_str,
            "current_size": current_size,
            "current_size_str": current_size_str,
            "current_count": current_count,
            "load_factor": load_factor,
        }

    def is_local(self, filepath):
        """Determines whether the given filepath is local.

        Args:
            filepath: a filepath

        Returns:
            True/False
        """
        fs = fos.get_file_system(filepath)
        return fs == fos.FileSystem.LOCAL

    def is_local_or_cached(self, filepath):
        """Determines whether the given filepath is either local or a remote
        file that has been cached.

        Args:
            filepath: a filepath

        Returns:
            True/False
        """
        fs, _, exists, _ = self._parse_filepath(filepath)
        return fs == fos.FileSystem.LOCAL or exists

    def use_cached_path(self, filepath):
        """Returns the local cache path for the given filepath, if it exists,
        otherwise returns the filepath itself.

        Args:
            filepath: a filepath

        Returns:
            a tuple of:
            -   the (possibly locally-cached) filepath
            -   True/False whether the returned path is local
        """

        # Function will report exists as True if we have previously
        #   failed to download it, so we must override that protection. In this
        #   function, we'd prefer to err on the side of returning the original
        #   unless we're certain the local path exists.
        fs, local_path, exists, _ = self._parse_filepath(
            filepath, check_exists=True, override_retry_protection=True
        )
        if fs == fos.FileSystem.LOCAL or exists:
            return local_path, True
        else:
            return filepath, False

    def use_cached_paths(self, filepaths):
        """Returns the local cache path for each filepath, if it exists,
        otherwise returns the input filepath.

        Args:
            filepaths: a list of filepaths

        Returns:
            a tuple of:
            -   a list of (possibly locally-cached) filepaths
            -   True/False whether all returned paths are local
        """
        cached_paths = []
        all_local = True

        for filepath in filepaths:
            cached_path, is_local = self.use_cached_path(filepath)
            cached_paths.append(cached_path)
            all_local &= is_local

        return cached_paths, all_local

    def get_remote_file_metadata(self, filepath, skip_failures=True):
        """Retrieves the file metadata for the given remote file, if possible.

        The returned value may be ``None`` if file metadata could not be
        retrieved.

        Args:
            filepath: a filepath
            skip_failures (True): whether to gracefully continue without
                raising an error if a file's metadata cannot be computed

        Returns:
            a file metdata dict or ``None``
        """
        client = fos.get_client(path=filepath)

        task = (client, filepath, skip_failures)
        _, metadata = _do_get_file_metadata(task)

        return metadata

    def get_remote_file_metadatas(
        self,
        filepaths,
        skip_failures=True,
        progress=None,
    ):
        """Returns a dictionary mapping any uncached remote filepaths in the
        provided list to file metadata dicts retrieved from the remote source.

        Values may be ``None`` if file metadata could not be retrieved for a
        given file.

        Args:
            filepaths: an iterable of filepaths
            skip_failures (True): whether to gracefully continue without
                raising an error if a file's metadata cannot be computed
            progress (None): whether to render a progress bar (True/False), use
                the default value ``fiftyone.config.show_progress_bars``
                (None), or a progress callback function to invoke instead

        Returns:
            a dict mapping filepaths to file metadata dicts or ``None``
        """
        tasks = []
        seen = set()
        for filepath in filepaths:
            fs, _, exists, client = self._parse_filepath(filepath)
            if fs == fos.FileSystem.LOCAL or filepath in seen:
                continue

            seen.add(filepath)

            if not exists:
                tasks.append((client, filepath, skip_failures))

        if not tasks:
            return {}

        return _get_file_metadata(tasks, self.num_workers, progress)

    def get_remote_metadata(self, filepath, skip_failures=True):
        """Retrieves the :class:`fiftyone.core.metadata.Metadata` instance for
        the given remote file.

        Args:
            filepath: a filepath
            skip_failures (True): whether to gracefully continue without
                raising an error if a file's metadata cannot be computed

        Returns:
            a :class:`fiftyone.core.metadata.Metadata` or ``None``
        """
        task = (filepath, skip_failures)
        _, metadata = _do_get_metadata(task)

        return metadata

    def get_remote_metadatas(
        self, filepaths, skip_failures=True, progress=None
    ):
        """Returns a dictionary mapping any uncached remote filepaths in the
        provided list to :class:`fiftyone.core.metadata.Metadata` instances
        computed from the remote source.

        Values may be ``None`` if metadata could not be retrieved for a given
        file.

        Args:
            filepaths: an iterable of filepaths
            skip_failures (True): whether to gracefully continue without
                raising an error if a remote file's metadata cannot be computed
            progress (None): whether to render a progress bar (True/False), use
                the default value ``fiftyone.config.show_progress_bars``
                (None), or a progress callback function to invoke instead

        Returns:
            a dict mapping remote filepaths to
            :class:`fiftyone.core.metadata.Metadata` instances or ``None``
        """
        tasks = []
        seen = set()
        for filepath in filepaths:
            fs, local_path, exists, client = self._parse_filepath(filepath)
            if fs == fos.FileSystem.LOCAL or filepath in seen:
                continue

            seen.add(filepath)

            if not exists:
                tasks.append((client, filepath, skip_failures))

        if not tasks:
            return {}

        return _get_metadata(tasks, self.num_workers, progress)

    def get_local_path(self, filepath, download=True, skip_failures=True):
        """Retrieves the local path for the given file.

        Args:
            filepath: a filepath
            download (True): whether to download uncached remote files
            skip_failures (True): whether to gracefully continue without
                raising an error if a remote file cannot be downloaded

        Returns:
            the local filepath
        """
        _, local_path, exists, client = self._parse_filepath(
            filepath, check_exists=download
        )

        if download and not exists:
            task = (client, filepath, local_path, skip_failures, False)
            _do_download_media(task)

        return local_path

    async def _async_get_local_path(
        self, filepath, session, download=True, skip_failures=True
    ):
        _, local_path, exists, client = self._parse_filepath(
            filepath, check_exists=download
        )

        if download and not exists:
            task = (client, session, filepath, local_path, skip_failures)
            await _do_async_download_media(task)

        return local_path

    def get_local_paths(
        self,
        filepaths,
        download=True,
        skip_failures=True,
        progress=None,
    ):
        """Retrieves the local paths for the given files.

        Args:
            filepaths: an iterable of filepaths
            download (True): whether to download uncached remote files
            skip_failures (True): whether to gracefully continue without
                raising an error if a remote file cannot be downloaded
            progress (None): whether to render a progress bar (True/False), use
                the default value ``fiftyone.config.show_progress_bars``
                (None), or a progress callback function to invoke instead

        Returns:
            the list of local filepaths
        """
        local_paths = []
        tasks = []
        seen = set()
        for filepath in filepaths:
            fs, local_path, exists, client = self._parse_filepath(
                filepath, check_exists=download
            )
            local_paths.append(local_path)

            if fs == fos.FileSystem.LOCAL or filepath in seen:
                continue

            seen.add(filepath)

            if download and not exists:
                task = (client, filepath, local_path, skip_failures, False)
                tasks.append(task)

        if tasks:
            _download_media(tasks, self.num_workers, progress)

        return local_paths

    def add(
        self,
        filepaths,
        remote_paths,
        method="copy",
        overwrite=True,
        skip_failures=True,
        progress=None,
    ):
        """Adds the given files to your local media cache and associates them
        with the given remote paths.

        .. note::

            This method does not access the remote paths; they are simply
            assumed to exist. As a result, this method does not populate cache
            checksums, and thus calling :meth:`update` will redownload the
            files from their remote paths.

        Args:
            filepaths: an iterable of media paths
            remote_paths: an iterable of associated remote media paths
            method ("copy"): whether to ``"copy"`` or ``"move"`` the files into
                the cache
            overwrite (True): whether to overwrite (True) or skip (False)
                already cached files
            skip_failures (True): whether to gracefully continue without
                raising an error if a file cannot be cached
            progress (None): whether to render a progress bar (True/False), use
                the default value ``fiftyone.config.show_progress_bars``
                (None), or a progress callback function to invoke instead
        """
        supported_methods = ("copy", "move")
        if method not in supported_methods:
            raise ValueError(
                "Unsupported method=%s. The supported values are %s"
                % (method, supported_methods)
            )

        tasks = []
        for filepath, remote_path in zip(filepaths, remote_paths):
            # We must manually check for cache existence to avoid fancy logic
            # in `_parse_filepath()` that is intended to avoid download retries
            _, local_path, _, _ = self._parse_filepath(
                remote_path, check_exists=False
            )
            exists = os.path.isfile(local_path)

            if not exists or overwrite:
                task = (
                    filepath,
                    local_path,
                    remote_path,
                    method,
                    skip_failures,
                )
                tasks.append(task)

        if tasks:
            _cache_media(tasks, self.num_workers, progress)

    def get_url(self, remote_path, method="GET", hours=None):
        """Retrieves a URL for accessing the given remote file.

        Note that GCS, S3 and Azure URLs are signed URLs that will expire.

        For more information on signed URLs, check ``storage.get_url``


        Args:
            remote_path: the remote path
            method ("GET"): a valid HTTP method for signed URLs
            hours (None): a TTL for signed URLs. If not set, set to
                the default value in ``fo.config.signed_url_expiration``
        """
        fs = fos.get_file_system(remote_path)

        if fs == fos.FileSystem.LOCAL:
            raise ValueError(
                "Cannot get URL for local file '%s'" % remote_path
            )

        hours = hours or fo.config.signed_url_expiration

        client = fos.get_client(path=remote_path)
        return _get_url(client, remote_path, method=method, hours=hours)

    def update(self, filepaths=None, skip_failures=True, progress=None):
        """Re-downloads any cached files whose checksum no longer matches their
        remote source.

        Cached files whose remote source have been deleted are also deleted
        from the cache.

        If a remote client doesn't support checksums, all of its files will be
        re-downloaded.

        Args:
            filepaths (None): an iterable of remote files to check for updates.
                By default, the entire cache is updated
            skip_failures (True): whether to gracefully continue without
                raising an error if a remote file cannot be downloaded
            progress (None): whether to render a progress bar (True/False), use
                the default value ``fiftyone.config.show_progress_bars``
                (None), or a progress callback function to invoke instead
        """
        if filepaths is None:
            filepaths = _get_cached_filepaths(self)

        tasks = []
        seen = set()
        for filepath in filepaths:
            fs, local_path, _, client = self._parse_filepath(
                filepath, check_exists=False
            )
            if fs == fos.FileSystem.LOCAL or filepath in seen:
                continue

            seen.add(filepath)
            tasks.append((client, filepath))

        if not tasks:
            return

        checksums = _get_checksums(tasks, self.num_workers, progress)

        tasks = []
        for filepath, checksum in checksums.items():
            fs, local_path, _, client = self._parse_filepath(
                filepath, check_exists=False
            )

            result = _get_cache_result(local_path)
            if result is not None:
                _, success, cached_checksum = result
            else:
                success = True
                cached_checksum = None

            if success and checksum is None:
                # We were previously able to download the file but now failed
                # to retrieve its checksum, assume the file was deleted
                _pop_cache(local_path)
            elif cached_checksum != checksum or not checksum:
                #
                # Any of the following things may have happened
                #   - The checksum changed
                #   - The remote download failed previously
                #   - The remote client doesn't support checksums
                #
                # In all cases, we need to re-download now
                #
                task = (client, filepath, local_path, skip_failures, True)
                tasks.append(task)

        if tasks:
            _download_media(tasks, self.num_workers, progress)

    def garbage_collect(self, _logger=None):
        """Executes the cache's garbage collection routine.

        This will delete any orphan files from the cache directory, as well as
        the oldest files, if necessary, if the cache's total size exceeds its
        limit.
        """
        if _logger is None:
            _logger = logger

        _garbage_collect_cache(self, _logger)

    def clear(self, filepaths=None):
        """Deletes all or specific files from the cache.

        Args:
            filepaths (None): an iterable of filepaths to delete, if necessary.
                By default, all cached files are deleted
        """
        if filepaths is None:
            if os.path.isdir(self.media_dir):
                etau.delete_dir(self.media_dir)
        else:
            # @todo delete empty directories after this operation?
            for filepath in filepaths:
                fs, local_path, exists, _ = self._parse_filepath(filepath)
                if fs != fos.FileSystem.LOCAL and exists:
                    _pop_cache(local_path)

    def _parse_filepath(
        self, filepath, check_exists=True, override_retry_protection=False
    ):
        fs = fos.get_file_system(filepath)

        # Always return `exists=True` for local filepaths
        if fs == fos.FileSystem.LOCAL:
            return fs, filepath, True, None

        client = fos.get_client(path=filepath)
        relpath = client.get_local_path(filepath)
        local_path = os.path.join(self.media_dir, fs, relpath)

        if not check_exists:
            return fs, local_path, None, client

        exists = os.path.isfile(local_path)

        # If the file does not exist and we were unable to download it in the
        # first place, report that the file exists to avoid retried downloads
        if not override_retry_protection and not exists:
            result = _get_cache_result(local_path)
            if result is not None:
                _, success, _ = result
                if not success:
                    exists = True

        return fs, local_path, exists, client


def _is_video(filepath):
    mime_type = etau.guess_mime_type(filepath)
    return mime_type.startswith("video/")


def _is_cache_path(path):
    return path.endswith(".cache")


def _get_cache_path(local_path):
    return os.path.splitext(local_path)[0] + ".cache"


def _get_cache_result(local_path):
    cache_path = _get_cache_path(local_path)
    try:
        return _read_cache_result(cache_path)
    except FileNotFoundError:
        return None


def _read_cache_result(cache_path):
    with open(cache_path, "r") as f:
        chunks = f.read().split(",")
        if len(chunks) > 3:
            filepath = ",".join(chunks[:-2])
            success_str, checksum = chunks[-2:]
        else:
            filepath, success_str, checksum = chunks

        success = success_str == "1"
        return filepath, success, checksum


def _write_cache_result(filepath, local_path, success, checksum):
    cache_path = _get_cache_path(local_path)
    etau.ensure_dir(os.path.dirname(cache_path))
    with open(cache_path, "w") as f:
        f.write("%s,%d,%s" % (filepath, int(success), checksum or ""))


def _garbage_collect_cache(gc_media_cache, gc_logger):
    gc_logger.info("Running garbage collection")

    media_dir = gc_media_cache.media_dir
    cache_size = gc_media_cache.cache_size
    lock_path = gc_media_cache._lock_path

    if _is_cache_locked(lock_path, gc_logger):
        gc_logger.info("Aborting garbage collection")
        return

    try:
        _lock_cache(lock_path)
        _do_garbage_collection(media_dir, cache_size, gc_logger)
    except Exception as e:
        gc_logger.error(e)
    finally:
        _unlock_cache(lock_path)


def _is_cache_locked(lock_path, gc_logger):
    try:
        with open(lock_path, "r") as f:
            lock_time = datetime.fromtimestamp(int(f.read()))
            lock_delta = datetime.utcnow() - lock_time
            thresh_delta = timedelta(minutes=1)

            if lock_delta < thresh_delta:
                gc_logger.info(
                    "The cache was locked at %s (%s ago)",
                    lock_time,
                    lock_delta,
                )
                return True

            gc_logger.info(
                "The cache was locked at %s (%s >= %s ago) and never "
                "unlocked, so we're force-unlocking it now",
                lock_time,
                lock_delta,
                thresh_delta,
            )
            return False
    except:
        return False


def _lock_cache(lock_path):
    with open(lock_path, "w") as f:
        f.write(str(int(datetime.utcnow().timestamp())))


def _unlock_cache(lock_path):
    _delete_file(lock_path)


def _do_garbage_collection(media_dir, cache_size, gc_logger):
    if cache_size < 0:
        cache_size = float("inf")

    paths = etau.list_files(media_dir, recursive=True, sort=False)

    media_roots = set(
        os.path.splitext(path)[0] for path in paths if not _is_cache_path(path)
    )

    current_count = 0
    current_size = 0
    orphan_cache_files = 0
    deleted_count = 0
    deleted_size = 0

    results = []
    for path in paths:
        if _is_cache_path(path):
            root = os.path.splitext(path)[0]
            if root not in media_roots:
                # Found cache file with no corresponding media
                orphan_cache_files += 1
                cache_path = os.path.join(media_dir, path)
                _delete_file(cache_path)
        else:
            local_path = os.path.join(media_dir, path)
            cache_path = _get_cache_path(local_path)

            stat = os.stat(local_path)
            size_bytes = stat.st_size

            try:
                _read_cache_result(cache_path)
                atime = stat.st_atime
            except:
                # Found media with missing or invalid cache file
                #   If file was modified recently, let's leave it alone.
                #   It might be a temp file used by the download client.
                #   We don't want to pull the rug from under it.
                if (time.time() - stat.st_mtime) < 60 * 60:
                    atime = stat.st_atime
                else:
                    atime = -1

            current_count += 1
            current_size += size_bytes
            results.append((local_path, size_bytes, atime))

    for local_path, size_bytes, atime in sorted(results, key=lambda r: r[2]):
        if current_size <= cache_size and atime > 0:
            break

        _pop_cache(local_path)

        current_count -= 1
        current_size -= size_bytes
        deleted_count += 1
        deleted_size += 1

    # @todo delete empty directories from cache here

    if deleted_count > 0:
        gc_logger.info(
            "Deleted %d media files (%s)",
            deleted_count,
            etau.to_human_bytes_str(deleted_size),
        )

    if orphan_cache_files > 0:
        gc_logger.info("Deleted %d orphan cache files", orphan_cache_files)

    if deleted_count == 0 and orphan_cache_files == 0:
        gc_logger.info("Nothing to cleanup")

    gc_logger.info(
        "Garbage collection complete; the cache size is %d media files (%s)",
        current_count,
        etau.to_human_bytes_str(current_size),
    )


def _get_cached_filepaths(_media_cache):
    media_dir = _media_cache.media_dir
    paths = etau.list_files(media_dir, recursive=True, sort=False)

    filepaths = []
    for path in paths:
        if _is_cache_path(path):
            cache_path = os.path.join(media_dir, path)
            filepath = _read_cache_result(cache_path)[0]
            filepaths.append(filepath)

    return filepaths


def _compute_cache_stats(_media_cache, filepaths=None):
    current_count = 0
    current_size = 0

    if filepaths is not None:
        for filepath in set(filepaths):
            fs, local_path, exists, _ = _media_cache._parse_filepath(filepath)
            if fs != fos.FileSystem.LOCAL and exists:
                try:
                    current_size += os.path.getsize(local_path)
                    current_count += 1
                except FileNotFoundError:
                    pass
    else:
        media_dir = _media_cache.media_dir
        paths = etau.list_files(media_dir, recursive=True, sort=False)

        for path in paths:
            if not _is_cache_path(path):
                local_path = os.path.join(media_dir, path)
                current_size += os.path.getsize(local_path)
                current_count += 1

    return current_count, current_size


def _pop_cache(local_path):
    cache_path = _get_cache_path(local_path)
    _delete_file(local_path)
    _delete_file(cache_path)


def _delete_file(local_path):
    try:
        os.remove(local_path)
    except FileNotFoundError:
        pass


def _download_media(tasks, num_workers, progress):
    progress = _parse_progress(progress)

    if progress:
        logger.info("Downloading media...")

    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(progress=progress) as pb:
            for task in pb(tasks):
                _do_download_media(task)
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=len(tasks), progress=progress) as pb:
                results = pool.imap_unordered(_do_download_media, tasks)
                for _ in pb(results):
                    pass


def _do_download_media(arg):
    client, remote_path, local_path, skip_failures, force = arg

    success = True
    if force or not os.path.isfile(local_path):
        try:
            client.download(remote_path, local_path)
        except Exception as e:
            if not skip_failures:
                raise

            logger.warning(e)
            success = False

    if success:
        _, checksum = _do_get_checksum((client, remote_path))
    else:
        checksum = None

    _write_cache_result(remote_path, local_path, success, checksum)


def _cache_media(tasks, num_workers, progress):
    num_tasks = len(tasks)

    if num_tasks == 1:
        _do_cache_media(tasks[0])
        return

    progress = _parse_progress(progress)

    if progress:
        logger.info("Caching media...")

    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(total=num_tasks, progress=progress) as pb:
            for task in pb(tasks):
                _do_cache_media(task)
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=num_tasks, progress=progress) as pb:
                results = pool.imap_unordered(_do_cache_media, tasks)
                for _ in pb(results):
                    pass


def _do_cache_media(args):
    filepath, local_path, remote_path, method, skip_failures = args

    success = True
    try:
        if method == "move":
            fos.move_file(filepath, local_path)
        else:
            fos.copy_file(filepath, local_path)
    except Exception as e:
        if not skip_failures:
            raise

        logger.warning(e)
        success = False

    _write_cache_result(remote_path, local_path, success, None)


async def _do_async_download_media(arg):
    client, session, remote_path, local_path, skip_failures = arg

    url = _get_url(client, remote_path)
    url = _safe_aiohttp_url(url)

    etau.ensure_basedir(local_path)

    success = True
    checksum = None

    try:
        checksum = await _do_download_file(session, url, local_path)
    except Exception as e:
        if not skip_failures:
            raise

        logger.warning(e)
        success = False

    await _async_write_cache_result(remote_path, local_path, success, checksum)


@backoff.on_exception(
    backoff.expo,
    aiohttp.ClientResponseError,
    factor=HTTPRetryConfig.FACTOR,
    max_tries=HTTPRetryConfig.MAX_TRIES,
    giveup=lambda e: e.status not in HTTPRetryConfig.RETRY_CODES,
    logger=None,
)
async def _do_download_file(session, url, local_path):
    async with session.get(url) as r:
        r.raise_for_status()
        checksum = r.headers.get("Etag", None)
        if checksum:
            checksum = checksum[1:-1]

        async with aiofiles.open(local_path, "wb") as f:
            async for chunk, _ in r.content.iter_chunks():
                await f.write(chunk)

    return checksum


def _safe_aiohttp_url(url):
    if urlparse.unquote(url) == url:
        return url

    # The `aiohttp` library improperly handles things like signed URLs for
    # objects containing special characters like `:`, so we must mark the URL
    # as already encoded
    # https://docs.aiohttp.org/en/stable/client_quickstart.html#passing-parameters-in-urls
    return yarl.URL(url, encoded=True)


async def _async_write_cache_result(filepath, local_path, success, checksum):
    cache_path = _get_cache_path(local_path)
    async with aiofiles.open(cache_path, "w") as f:
        await f.write("%s,%d,%s" % (filepath, int(success), checksum or ""))


def _get_checksums(tasks, num_workers, progress):
    checksums = {}

    progress = _parse_progress(progress)

    if progress:
        logger.info("Getting checksums...")

    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(progress=progress) as pb:
            for task in pb(tasks):
                filepath, checksum = _do_get_checksum(task)
                checksums[filepath] = checksum
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=len(tasks), progress=progress) as pb:
                results = pool.imap_unordered(_do_get_checksum, tasks)
                for filepath, checksum in pb(results):
                    checksums[filepath] = checksum

    return checksums


def _do_get_checksum(arg):
    client, remote_path = arg

    if hasattr(client, "get_file_metadata"):
        try:
            metadata = client.get_file_metadata(remote_path)
            checksum = metadata["etag"]
        except:
            checksum = None
    else:
        checksum = ""

    return remote_path, checksum


def _get_file_metadata(tasks, num_workers, progress):
    metadata = {}

    progress = _parse_progress(progress)

    if progress:
        logger.info("Getting file metadata...")

    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(progress=progress) as pb:
            for task in pb(tasks):
                filepath, _meta = _do_get_file_metadata(task)
                metadata[filepath] = _meta
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=len(tasks), progress=progress) as pb:
                results = pool.imap_unordered(_do_get_file_metadata, tasks)
                for filepath, _meta in pb(results):
                    metadata[filepath] = _meta

    return metadata


def _do_get_file_metadata(arg):
    client, remote_path, skip_failures = arg

    try:
        metadata = client.get_file_metadata(remote_path)
    except Exception as e:
        if not skip_failures:
            raise

        logger.warning(e)
        metadata = None

    return remote_path, metadata


def _get_metadata(tasks, num_workers, progress):
    metadata = {}

    progress = _parse_progress(progress)

    if progress:
        logger.info("Getting metadata...")

    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(progress=progress) as pb:
            for task in pb(tasks):
                filepath, _meta = _do_get_metadata(task)
                metadata[filepath] = _meta
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=len(tasks), progress=progress) as pb:
                results = pool.imap_unordered(_do_get_metadata, tasks)
                for filepath, _meta in pb(results):
                    metadata[filepath] = _meta

    return metadata


def _do_get_metadata(arg):
    remote_path, skip_failures = arg

    mime_type = etau.guess_mime_type(remote_path)

    try:
        if mime_type.startswith("video"):
            metadata = fom.VideoMetadata.build_for(
                remote_path, mime_type=mime_type
            )
        elif mime_type.startswith("image"):
            metadata = fom.ImageMetadata.build_for(
                remote_path, mime_type=mime_type
            )
        else:
            metadata = fom.Metadata.build_for(remote_path, mime_type=mime_type)
    except Exception as e:
        if not skip_failures:
            raise

        logger.warning(e)
        metadata = None

    return remote_path, metadata


def _get_url(client, remote_path, **kwargs):
    if hasattr(client, "generate_signed_url"):
        return client.generate_signed_url(remote_path, **kwargs)

    return remote_path


def _parse_progress(progress):
    if progress is None:
        return fo.config.show_progress_bars

    return progress
