"""
File storage utilities.

| Copyright 2017-2024, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
import io
import itertools
import json
import logging
import multiprocessing.dummy
import ntpath
import os
import posixpath
import re
import shutil
import tempfile
import threading
import urllib.parse as urlparse

import bson
import jsonlines
from wcmatch import glob
import yaml

import eta.core.serial as etase
import eta.core.storage as etast
import eta.core.utils as etau

import fiftyone as fo
import fiftyone.core.media as fom
import fiftyone.core.utils as fou
import fiftyone.internal as fi
import fiftyone.internal.constants as fic

foc = fou.lazy_import("fiftyone.core.cache")
fo3d = fou.lazy_import("fiftyone.core.threed")
fou3d = fou.lazy_import("fiftyone.utils.utils3d")


logger = logging.getLogger(__name__)

creds_manager = None
available_file_systems = None
default_clients = {}
bucket_regions = {}
region_clients = {}
bucket_clients = {}
path_clients = {}
client_lock = threading.Lock()
minio_prefixes = []
azure_prefixes = []

S3_PREFIX = "s3://"
GCS_PREFIX = "gs://"
HTTP_PREFIX = "http://"
HTTPS_PREFIX = "https://"


def init_storage():
    """Initializes storage client use.

    This method may be called at any time to reinitialize storage client usage.
    """
    global creds_manager
    if fi.has_encryption_key():
        from fiftyone.internal.credentials import CloudCredentialsManager

        encryption_key = os.environ.get(fic.ENCRYPTION_KEY_ENV_VAR)
        creds_manager = CloudCredentialsManager(encryption_key)
    else:
        creds_manager = None

    global available_file_systems
    available_file_systems = None

    default_clients.clear()
    bucket_regions.clear()
    region_clients.clear()
    bucket_clients.clear()
    path_clients.clear()
    minio_prefixes.clear()
    azure_prefixes.clear()

    _load_minio_prefixes()
    _load_azure_prefixes()


def _load_minio_prefixes():
    minio_creds = []

    # Check database for credentials
    if creds_manager is not None:
        creds_paths = creds_manager.get_all_credentials_for_file_system(
            FileSystem.MINIO
        )
        for creds_path in creds_paths:
            credentials, _ = MinIOStorageClient.load_credentials(
                credentials_path=creds_path
            )

            if credentials:
                minio_creds.append(credentials)

    # Check environment for credentials
    credentials_path = fo.media_cache_config.minio_config_file
    profile = fo.media_cache_config.minio_profile

    credentials, _ = MinIOStorageClient.load_credentials(
        credentials_path=credentials_path, profile=profile
    )
    if credentials:
        minio_creds.append(credentials)

    # Register prefixes
    for credentials in minio_creds:
        minio_alias_prefix = None
        minio_endpoint_prefix = None

        if "alias" in credentials:
            minio_alias_prefix = credentials["alias"] + "://"

        if "endpoint_url" in credentials:
            minio_endpoint_prefix = (
                credentials["endpoint_url"].rstrip("/") + "/"
            )

        # Maintain order so default credentials are first, if multiple
        prefixes = (minio_alias_prefix, minio_endpoint_prefix)
        if prefixes not in minio_prefixes:
            minio_prefixes.append(prefixes)


def _load_azure_prefixes():
    azure_creds = []

    # Check database for credentials
    if creds_manager is not None:
        creds_paths = creds_manager.get_all_credentials_for_file_system(
            FileSystem.AZURE
        )
        for creds_path in creds_paths:
            credentials, _ = AzureStorageClient.load_credentials(
                credentials_path=creds_path
            )

            if credentials:
                azure_creds.append(credentials)

    # Check environment for credentials
    credentials_path = fo.media_cache_config.azure_credentials_file
    azure_profile = fo.media_cache_config.azure_profile

    credentials, _ = AzureStorageClient.load_credentials(
        credentials_path=credentials_path, profile=azure_profile
    )
    if credentials:
        azure_creds.append(credentials)

    # Register prefixes
    for credentials in azure_creds:
        azure_alias_prefix = None
        azure_endpoint_prefix = None

        if "alias" in credentials:
            azure_alias_prefix = credentials["alias"] + "://"

        if "account_url" in credentials:
            azure_endpoint_prefix = (
                credentials["account_url"].rstrip("/") + "/"
            )
        elif "conn_str" in credentials or "account_name" in credentials:
            account_url = AzureStorageClient._to_account_url(
                conn_str=credentials.get("conn_str", None),
                account_name=credentials.get("account_name", None),
            )
            azure_endpoint_prefix = account_url.rstrip("/") + "/"

        # Maintain order so default credentials are first, if multiple
        prefixes = (azure_alias_prefix, azure_endpoint_prefix)
        if prefixes not in azure_prefixes:
            azure_prefixes.append(prefixes)


class FileSystem(object):
    """Enumeration of the available file systems."""

    S3 = "s3"
    GCS = "gcs"
    AZURE = "azure"
    MINIO = "minio"
    HTTP = "http"
    LOCAL = "local"


_FILE_SYSTEMS_WITH_BUCKETS = {
    FileSystem.S3,
    FileSystem.GCS,
    FileSystem.AZURE,
    FileSystem.MINIO,
}
_FILE_SYSTEMS_WITH_ALIASES = {FileSystem.AZURE, FileSystem.MINIO}
_FILE_SYSTEMS_WITH_REGIONAL_CLIENTS = {FileSystem.S3, FileSystem.MINIO}
_UNKNOWN_REGION = "unknown"


class S3StorageClient(etast.S3StorageClient):
    """.. autoclass:: eta.core.storage.S3StorageClient"""

    def get_local_path(self, remote_path):
        return self._strip_prefix(remote_path)


class GoogleCloudStorageClient(etast.GoogleCloudStorageClient):
    """.. autoclass:: eta.core.storage.GoogleCloudStorageClient"""

    def get_local_path(self, remote_path):
        return self._strip_prefix(remote_path)


class AzureStorageClient(etast.AzureStorageClient):
    """.. autoclass:: eta.core.storage.AzureStorageClient"""

    def get_local_path(self, remote_path):
        return self._strip_prefix(remote_path)


class MinIOStorageClient(etast.MinIOStorageClient):
    """.. autoclass:: eta.core.storage.MinIOStorageClient"""

    def get_local_path(self, remote_path):
        return self._strip_prefix(remote_path)


class HTTPStorageClient(etast.HTTPStorageClient):
    """.. autoclass:: eta.core.storage.HTTPStorageClient"""

    def get_local_path(self, remote_path):
        p = urlparse.urlparse(remote_path)

        if p.port is not None:
            host = "%s:%d" % (p.hostname, p.port)
        else:
            host = p.hostname

        return os.path.join(host, *p.path.lstrip("/").split("/"))


def get_file_system(path):
    """Returns the file system enum for the given path.

    Args:
        path: a path

    Returns:
        a :class:`FileSystem` value
    """
    _refresh_managed_credentials_if_necessary()

    if not path:
        return FileSystem.LOCAL

    # Check MinIO and Azure first in case alias/endpoint clashes with another
    # file system

    for minio_alias_prefix, minio_endpoint_prefix in minio_prefixes:
        if (
            minio_alias_prefix is not None
            and path.startswith(minio_alias_prefix)
        ) or (
            minio_endpoint_prefix is not None
            and path.startswith(minio_endpoint_prefix)
        ):
            return FileSystem.MINIO

    for azure_alias_prefix, azure_endpoint_prefix in azure_prefixes:
        if (
            azure_alias_prefix is not None
            and path.startswith(azure_alias_prefix)
        ) or (
            azure_endpoint_prefix is not None
            and path.startswith(azure_endpoint_prefix)
        ):
            return FileSystem.AZURE

    if path.startswith(S3_PREFIX):
        return FileSystem.S3

    if path.startswith(GCS_PREFIX):
        return FileSystem.GCS

    if path.startswith((HTTP_PREFIX, HTTPS_PREFIX)):
        return FileSystem.HTTP

    return FileSystem.LOCAL


def list_available_file_systems():
    """Lists the file systems that are currently available for use with methods
    like :func:`list_files` and :func:`list_buckets`.

    Returns:
        a list of :class:`FileSystem` values
    """
    _refresh_managed_credentials_if_necessary()

    global available_file_systems

    if available_file_systems is None:
        available_file_systems = _get_available_file_systems()

    return available_file_systems


def _get_available_file_systems():
    file_systems = set()

    if not fi.is_internal_service():
        file_systems.add(FileSystem.LOCAL)

    managed_file_systems = _get_file_systems_with_managed_credentials()
    if managed_file_systems:
        file_systems.update(managed_file_systems)

    for fs in _FILE_SYSTEMS_WITH_BUCKETS:
        if fs in file_systems:
            continue

        try:
            _ = get_client(fs=fs)
            file_systems.add(fs)
        except:
            pass

    return sorted(file_systems)


def split_prefix(path):
    """Splits the file system prefix from the given path.

    The prefix for local paths is ``""``.

    Example usages::

        import fiftyone.core.storage as fos

        fos.split_prefix("s3://bucket/object")  # ('s3://', 'bucket/object')
        fos.split_prefix("gs://bucket/object")  # ('g3://', 'bucket/object')
        fos.split_prefix("/path/to/file")       # ('', '/path/to/file')
        fos.split_prefix("a/file")              # ('', 'a/file')

    Args:
        path: a path

    Returns:
        a ``(prefix, path)`` tuple
    """
    fs = get_file_system(path)
    return _split_prefix(fs, path)


def _split_prefix(fs, path):
    prefix = None
    if fs == FileSystem.S3:
        prefix = S3_PREFIX
    elif fs == FileSystem.GCS:
        prefix = GCS_PREFIX
    elif fs == FileSystem.MINIO:
        for minio_alias_prefix, minio_endpoint_prefix in minio_prefixes:
            if minio_alias_prefix is not None and path.startswith(
                minio_alias_prefix
            ):
                prefix = minio_alias_prefix
            elif minio_endpoint_prefix is not None and path.startswith(
                minio_endpoint_prefix
            ):
                prefix = minio_endpoint_prefix

            if prefix is not None:
                break
    elif fs == FileSystem.AZURE:
        for azure_alias_prefix, azure_endpoint_prefix in azure_prefixes:
            if azure_alias_prefix is not None and path.startswith(
                azure_alias_prefix
            ):
                prefix = azure_alias_prefix
            elif azure_endpoint_prefix is not None and path.startswith(
                azure_endpoint_prefix
            ):
                prefix = azure_endpoint_prefix

            if prefix is not None:
                break
    elif path.startswith(HTTP_PREFIX):
        prefix = HTTP_PREFIX
    elif path.startswith(HTTPS_PREFIX):
        prefix = HTTPS_PREFIX

    if prefix is None:
        prefix = ""

    return prefix, path[len(prefix) :]


def get_bucket_name(path):
    """Gets the bucket name from the given path.

    The bucket name for local paths and http(s) paths is ``""``.

    Example usages::

        import fiftyone.core.storage as fos

        fos.get_bucket_name("s3://bucket/object")  # 'bucket'
        fos.get_bucket_name("gs://bucket/object")  # 'bucket'
        fos.get_bucket_name("/path/to/file")       # ''
        fos.get_bucket_name("a/file")              # ''

    Args:
        path: a path

    Returns:
        the bucket name string
    """
    fs = get_file_system(path)

    bucket = _get_bucket(fs, path)
    return _get_bucket_name(bucket)


def _get_bucket(fs, path):
    if fs not in _FILE_SYSTEMS_WITH_BUCKETS:
        return ""

    prefix, path = _split_prefix(fs, path)
    bucket_name = path.split("/")[0]

    return prefix + bucket_name


def _get_bucket_name(bucket):
    return bucket.rsplit("/", 1)[-1]


def _swap_prefix(fs, bucket):
    bucket_name = _get_bucket_name(bucket)
    prefix = bucket[: -len(bucket_name)]

    if fs == FileSystem.AZURE:
        for azure_alias_prefix, azure_endpoint_prefix in azure_prefixes:
            if (
                prefix == azure_alias_prefix
                and azure_endpoint_prefix is not None
            ):
                return azure_endpoint_prefix + bucket_name

            if (
                prefix == azure_endpoint_prefix
                and azure_alias_prefix is not None
            ):
                return azure_alias_prefix + bucket_name

    if fs == FileSystem.MINIO:
        for minio_alias_prefix, minio_endpoint_prefix in minio_prefixes:
            if (
                prefix == minio_alias_prefix
                and minio_endpoint_prefix is not None
            ):
                return minio_endpoint_prefix + bucket_name

            if (
                prefix == minio_endpoint_prefix
                and minio_alias_prefix is not None
            ):
                return minio_alias_prefix + bucket_name

    return bucket


def is_local(path):
    """Determines whether the given path is local.

    Args:
        path: a path

    Returns:
        True/False
    """
    return get_file_system(path) == FileSystem.LOCAL


def ensure_local(path):
    """Ensures that the given path is local.

    Args:
        path: a path
    """
    if not is_local(path):
        raise ValueError(
            "The requested operation requires a local path, but found '%s'"
            % path
        )


def normalize_path(path):
    """Normalizes the given path.

    Local paths are sanitized via::

        os.path.abspath(os.path.expanduser(path))

    Remote paths are sanitized via::

        path.rstrip("/")

    Args:
        path: a path

    Returns:
        the normalized path
    """
    if is_local(path):
        return os.path.abspath(os.path.expanduser(path))

    return path.rstrip("/")


def get_client(fs=None, path=None):
    """Returns the storage client for the given file system or path.

    If a ``path`` is provided, a region-specific client is returned, if
    applicable. Otherwise, the client for the given file system is returned.

    Args:
        fs (None): a :class:`FileSystem` value
        path (None): a path

    Returns:
        a :class:`eta.core.storage.StorageClient`

    Raises:
        ValueError: if no suitable client could be constructed
    """
    return _get_client(fs=fs, path=path)


def get_url(path, **kwargs):
    """Returns a public URL for the given file.

    The provided path must either already be a URL or a path into a file system
    that supports signed URLs.

    Args:
        path: a path
        **kwargs: optional keyword arguments for the storage client's
            ``generate_signed_url(path, **kwargs)`` method

    Returns:
        a URL
    """
    fs = get_file_system(path)

    if fs == FileSystem.HTTP:
        return path

    client = get_client(path=path)

    if not hasattr(client, "generate_signed_url"):
        raise ValueError(
            "Cannot get URL for '%s'; file system '%s' does not support "
            "signed URLs" % (path, fs)
        )

    kwargs["hours"] = kwargs.get("hours", fo.config.signed_url_expiration)

    return client.generate_signed_url(path, **kwargs)


def to_readable(path, **kwargs):
    """Returns a publicly readable path for the given file.

    The provided path must either already be a URL or be a remote path into a
    file system that supports signed URLs.

    Args:
        path: a path
        **kwargs: optional keyword arguments for the storage client's
            ``generate_signed_url(path, **kwargs)`` method

    Returns:
        a public path
    """
    if is_local(path):
        return path

    return get_url(path, method="GET", **kwargs)


def to_writeable(path, **kwargs):
    """Returns a publicly writable path for the given file.

    The provided path must either already be a URL or be a remote path into a
    file system that supports signed URLs.

    Args:
        path: a path
        **kwargs: optional keyword arguments for the storage client's
            ``generate_signed_url(path, **kwargs)`` method

    Returns:
        a public path
    """
    if is_local(path):
        return path

    params = dict(method="PUT", content_type=etau.guess_mime_type(path))
    params.update(kwargs)

    return get_url(path, **params)


def make_temp_dir(basedir=None):
    """Makes a temporary directory.

    Args:
        basedir (None): an optional local or remote directory in which to
            create the new directory. The default is
            ``fiftyone.config.default_dataset_dir``

    Returns:
        the temporary directory path
    """
    if basedir is None:
        basedir = fo.config.default_dataset_dir

    if is_local(basedir):
        ensure_dir(basedir)
        return tempfile.mkdtemp(dir=basedir)

    return join(basedir, str(bson.ObjectId()))


class TempDir(object):
    """Context manager that creates and destroys a temporary directory.

    Args:
        basedir (None): an optional local or remote directory in which to
            create the new directory. The default is
            ``fiftyone.config.default_dataset_dir``
    """

    def __init__(self, basedir=None):
        self._basedir = basedir
        self._name = None

    def __enter__(self):
        self._name = make_temp_dir(basedir=self._basedir)
        return self._name

    def __exit__(self, *args):
        delete_dir(self._name)


class LocalDir(object):
    """Context manager that allows remote directory paths to be processed as
    local directory paths that can be passed to methods that don't natively
    support reading/writing remote locations.

    When a local directory is provided to this context manager, it is simply
    returned when the context is entered and no other operations are performed.

    When a remote directory is provided, a temporary local directory is
    returned when the context is entered, which is automatically deleted when
    the context exits. In addition:

    -   When ``mode == "r"``, the remote directory's contents is downloaded
        when the context is entered
    -   When ``mode == "w"``, the local directory's contents is uploaded to the
        remote directory when the context exits

    Example usage::

        import os

        import fiftyone.core.storage as fos

        with fos.LocalDir("s3://bucket/dir", "w") as local_dir:
            with open(os.path.join(local_dir, "file1.txt")) as f:
                f.write("Hello, world!")

            with open(os.path.join(local_dir, "file2.txt")) as f:
                f.write("Goodbye")

        with fos.LocalDir("s3://bucket/dir", "r") as local_dir:
            with open(os.path.join(local_dir, "file1.txt")) as f:
                print(f.read())

            with open(os.path.join(local_dir, "file2.txt")) as f:
                print(f.read())

    Args:
        path: a directory path
        mode ("r"): the mode. Supported values are ``("r", "w")``
        basedir (None): an optional directory in which to create temporary
            local directories
        skip_failures (False): whether to gracefully continue without raising
            an error if a remote upload/download fails
        type_str ("files"): the type of file being processed. Used only for
            log messages. If None/empty, nothing will be logged
        progress (None): whether to render a progress bar tracking the progress
            of any uploads/downloads (True/False), use the default value
            ``fiftyone.config.show_progress_bars`` (None), or a progress
            callback function to invoke instead
    """

    def __init__(
        self,
        path,
        mode="r",
        basedir=None,
        skip_failures=False,
        type_str="files",
        progress=None,
    ):
        if mode not in ("r", "w"):
            raise ValueError("Unsupported mode '%s'" % mode)

        if basedir is not None and not is_local(basedir):
            raise ValueError("basedir must be local; found '%s'" % basedir)

        self._path = path
        self._mode = mode
        self._basedir = basedir
        self._skip_failures = skip_failures
        self._type_str = type_str
        self._progress = progress
        self._tmpdir = None

    def __enter__(self):
        if is_local(self._path):
            return self._path

        self._tmpdir = make_temp_dir(basedir=self._basedir)

        if self._mode == "r":
            progress = _parse_progress(self._progress)

            if progress and self._type_str:
                logger.info("Downloading %s...", self._type_str)

            copy_dir(
                self._path,
                self._tmpdir,
                overwrite=False,
                skip_failures=self._skip_failures,
                progress=progress,
            )

        return self._tmpdir

    def __exit__(self, *args):
        if self._tmpdir is None:
            return

        try:
            if self._mode == "w":
                progress = _parse_progress(self._progress)

                if progress and self._type_str:
                    logger.info("Uploading %s...", self._type_str)

                copy_dir(
                    self._tmpdir,
                    self._path,
                    overwrite=False,
                    skip_failures=self._skip_failures,
                    progress=progress,
                )
        finally:
            etau.delete_dir(self._tmpdir)


class LocalFile(object):
    """Context manager that allows remote filepaths to be processed as local
    filepaths that can be passed to methods that don't natively support
    reading/writing remote locations.

    When a local filepath is provided to this context manager, it is simply
    returned when the context is entered and no other operations are performed.

    When a remote filepath is provided, a temporary local filepath is returned
    when the context is entered, which is automatically deleted when the
    context exits. In addition:

    -   When ``mode == "r"``, the remote file is downloaded when the context is
        entered
    -   When ``mode == "w"``, the local file is uploaded to the remote filepath
        when the context exits

    Example usage::

        import fiftyone.core.storage as fos

        with fos.LocalFile("s3://bucket/file.txt", "w") as local_path:
            with open(local_path, "w") as f:
                f.write("Hello, world!")

        with fos.LocalFile("s3://bucket/file.txt", "r") as local_path:
            with open(local_path, "r") as f:
                print(r.read())

    Args:
        path: a filepath
        mode ("r"): the mode. Supported values are ``("r", "w")``
        basedir (None): an optional directory in which to create temporary
            local files
    """

    def __init__(self, path, mode="r", basedir=None):
        if mode not in ("r", "w"):
            raise ValueError("Unsupported mode '%s'" % mode)

        if basedir is not None and not is_local(basedir):
            raise ValueError("basedir must be local; found '%s'" % basedir)

        self._path = path
        self._mode = mode
        self._basedir = basedir
        self._local_path = None
        self._tmpdir = None

    def __enter__(self):
        if is_local(self._path):
            return self._path

        self._tmpdir = make_temp_dir(basedir=self._basedir)
        self._local_path = os.path.join(
            self._tmpdir, os.path.basename(self._path)
        )

        if self._mode == "r":
            copy_file(self._path, self._local_path)

        return self._local_path

    def __exit__(self, *args):
        if self._tmpdir is None:
            return

        try:
            if self._mode == "w":
                copy_file(self._local_path, self._path)
        finally:
            etau.delete_dir(self._tmpdir)


class LocalFiles(object):
    """Context manager that allows lists of remote filepaths to be processed as
    local filepaths that can be passed to methods that don't natively support
    reading/writing remote locations.

    When local filepaths are provided to this context manager, they are simply
    returned when the context is entered and no other operations are performed.

    When remote filepaths are provided, temporary local filepaths are returned
    when the context is entered, which are automatically deleted when the
    context exits. In addition:

    -   When ``mode == "r"``, remote files are downloaded when the context is
        entered
    -   When ``mode == "w"``, local files are uploaded to their corresponding
        remote filepaths when the context exits

    Example usage::

        import fiftyone.core.storage as fos

        remote_paths = [
            "s3://bucket/file1.txt",
            "s3://bucket/file2.txt",
        ]

        with fos.LocalFiles(remote_paths, "w") as local_paths:
            for local_path in local_paths:
                with open(local_path, "w") as f:
                    f.write("Hello, world!")

        with fos.LocalFiles(remote_paths, "r") as local_paths:
            for local_path in local_paths:
                with open(local_path, "r") as f:
                    print(r.read())

    Args:
        paths: a list of filepaths, or a dict mapping keys to filepaths
        mode ("r"): the mode. Supported values are ``("r", "w", "rw")``
        basedir (None): an optional directory in which to create temporary
            local files
        skip_failures (False): whether to gracefully continue without raising
            an error if a remote upload/download fails
        type_str ("files"): the type of file being processed. Used only for
            log messages. If None/empty, nothing will be logged
        progress (None): whether to render a progress bar tracking the progress
            of any uploads/downloads (True/False), use the default value
            ``fiftyone.config.show_progress_bars`` (None), or a progress
            callback function to invoke instead
    """

    def __init__(
        self,
        paths,
        mode="r",
        basedir=None,
        skip_failures=False,
        type_str="files",
        progress=None,
    ):
        if not set(mode).issubset("rw"):
            raise ValueError("Unsupported mode '%s'" % mode)

        if basedir is not None and not is_local(basedir):
            raise ValueError("basedir must be local; found '%s'" % basedir)

        self._paths = paths
        self._mode = mode
        self._basedir = basedir
        self._skip_failures = skip_failures
        self._type_str = type_str
        self._progress = progress
        self._tmpdir = None
        self._filename_maker = None
        self._local_paths = None
        self._remote_paths = None

    def __enter__(self):
        local_paths = []
        remote_paths = []

        is_dict = isinstance(self._paths, dict)

        if is_dict:
            iter_paths = self._paths.items()
            _paths = {}
        else:
            iter_paths = self._paths
            _paths = []

        for path in iter_paths:
            if is_dict:
                key, path = path

            if not is_local(path):
                if self._tmpdir is None:
                    self._tmpdir = make_temp_dir(basedir=self._basedir)
                    self._filename_maker = fou.UniqueFilenameMaker()

                local_name = self._filename_maker.get_output_path(path)
                local_path = os.path.join(self._tmpdir, local_name)

                local_paths.append(local_path)
                remote_paths.append(path)
                path = local_path

            if is_dict:
                _paths[key] = path
            else:
                _paths.append(path)

        self._local_paths = local_paths
        self._remote_paths = remote_paths

        if "r" in self._mode and self._remote_paths:
            progress = _parse_progress(self._progress)

            if progress and self._type_str:
                logger.info("Downloading %s...", self._type_str)

            copy_files(
                self._remote_paths,
                self._local_paths,
                skip_failures=self._skip_failures,
                progress=progress,
            )

        return _paths

    def __exit__(self, *args):
        if self._tmpdir is None:
            return

        try:
            if "w" in self._mode and self._local_paths:
                progress = _parse_progress(self._progress)

                if progress and self._type_str:
                    logger.info("Uploading %s...", self._type_str)

                copy_files(
                    self._local_paths,
                    self._remote_paths,
                    skip_failures=self._skip_failures,
                    progress=progress,
                )
        finally:
            etau.delete_dir(self._tmpdir)


class DeleteFiles(object):
    """Context manager for efficiently deleting local or remote files.

    When local filepaths are provided to this context manager, they are
    immediately deleted.

    When remote filepaths are provided, they are efficiently deleted in a batch
    when the context exits.

    Example usage::

        import fiftyone.core.storage as fos

        remote_paths = [
            "s3://bucket/file1.txt",
            "s3://bucket/file2.txt",
        ]

        with fos.DeleteFiles() as df:
            for remote_path in remote_paths:
                df.delete(remote_path)

    Args:
        skip_failures (False): whether to gracefully continue without raising
            an error if a remote deletion fails
        type_str ("files"): the type of file being deleted. Used only for log
            messages. If None/empty, nothing will be logged
        progress (None): whether to render a progress bar tracking the progress
            of any deletions (True/False), use the default value
            ``fiftyone.config.show_progress_bars`` (None), or a progress
            callback function to invoke instead
    """

    def __init__(self, skip_failures=False, type_str="files", progress=None):
        self._skip_failures = skip_failures
        self._type_str = type_str
        self._progress = progress
        self._delpaths = None

    def delete(self, path):
        """Deletes the given file.

        Args:
            path: the filepath
        """
        if is_local(path):
            etau.delete_file(path)
        else:
            self._delpaths.append(path)

    def __enter__(self):
        self._delpaths = []
        return self

    def __exit__(self, *args):
        if self._delpaths:
            progress = _parse_progress(self._progress)

            if progress and self._type_str:
                logger.info("Deleting %s...", self._type_str)

            delete_files(
                self._delpaths,
                skip_failures=self._skip_failures,
                progress=progress,
            )


class FileWriter(object):
    """Context manager that allows writing remote files to disk locally first
    so that they can be efficiently uploaded to the remote destination in a
    batch.

    When local filepaths are provided to this context manager, they are simply
    returned verbatim.

    When remote filepaths are provided, temporary local filepaths are returned,
    which are then uploaded to their corresponding remote filepaths and then
    cleaned up when the context exits.

    Example usage::

        import fiftyone.core.storage as fos

        remote_paths = [
            "s3://bucket/file1.txt",
            "s3://bucket/file2.txt",
        ]

        with fos.FileWriter() as writer:
            for remote_path in remote_paths:
                local_path = writer.get_local_path(remote_path)
                with open(local_path, "w") as f:
                    f.write("Hello, world!")

    Args:
        basedir (None): an optional directory in which to create temporary
            local files
        skip_failures (False): whether to gracefully continue without raising
            an error if a remote upload fails
        type_str ("files"): the type of file being processed. Used only for
            log messages. If None/empty, nothing will be logged
        progress (None): whether to render a progress bar tracking the progress
            of any uploads (True/False), use the default value
            ``fiftyone.config.show_progress_bars`` (None), or a progress
            callback function to invoke instead
    """

    def __init__(
        self,
        basedir=None,
        skip_failures=False,
        type_str="files",
        progress=None,
        _progress_str=None,
        _use_cache=False,
    ):
        if basedir is not None and not is_local(basedir):
            raise ValueError("basedir must be local; found '%s'" % basedir)

        if _progress_str is None and type_str:
            _progress_str = "Uploading %s..." % type_str

        self._basedir = basedir
        self._skip_failures = skip_failures
        self._type_str = type_str
        self._progress = progress
        self._progress_str = _progress_str
        self._use_cache = _use_cache
        self._tmpdir = None
        self._filename_maker = None
        self._inpaths = None
        self._outpaths = None

    def __enter__(self):
        self._tmpdir = None
        self._filename_maker = None
        self._inpaths = []
        self._outpaths = []
        return self

    def __exit__(self, *args):
        try:
            if self._inpaths:
                progress = _parse_progress(self._progress)

                if progress and self._progress_str:
                    logger.info(self._progress_str)

                copy_files(
                    self._inpaths,
                    self._outpaths,
                    skip_failures=self._skip_failures,
                    use_cache=self._use_cache,
                    progress=progress,
                )
        finally:
            if self._tmpdir is not None:
                etau.delete_dir(self._tmpdir)

    def get_local_path(self, filepath):
        """Returns a local path on disk to write the given file.

        If the provided path is local, it is directly returned. If the path is
        remote, a temporary local path is returned.

        Args:
            filepath: a filepath

        Returns:
            the local filepath
        """
        if is_local(filepath):
            return filepath

        if self._tmpdir is None:
            self._tmpdir = make_temp_dir(basedir=self._basedir)
            self._filename_maker = fou.UniqueFilenameMaker()

        local_name = self._filename_maker.get_output_path(filepath)
        local_path = os.path.join(self._tmpdir, local_name)

        self._inpaths.append(local_path)
        self._outpaths.append(filepath)

        return local_path

    def get_local_paths(self, filepaths):
        """Returns local paths on disk for a list of filepaths.

        See :meth:`get_local_path` for details.

        Args:
            filepaths: a list of filepaths

        Returns:
            a list of local paths
        """
        return [self.get_local_path(p) for p in filepaths]

    def register_local_path(self, filepath, local_path):
        """Registers the local path for the given filepath.

        If the provided ``filepath`` is remote, it will be populated from the
        ``local_path`` you provide in the exit context's upload.

        If the provided ``filepath`` is local, this method has no effect.

        Args:
            filepath: a filepath
            local_path: a corresponding local path
        """
        if is_local(filepath):
            return

        self._inpaths.append(local_path)
        self._outpaths.append(filepath)

    def register_local_paths(self, filepaths, local_paths):
        """Registers the local paths for the given filepaths.

        Any remote paths in ``filepaths`` will be populated from the
        corresponding ``local_paths`` in the exit context's upload.

        Any local filepaths in ``filepaths`` are skipped.

        Args:
            filepaths: a list of filepaths
            local_paths: a list of corresponding local paths
        """
        for filepath, local_path in zip(filepaths, local_paths):
            self.register_local_path(filepath, local_path)

    def register_path(self, inpath, outpath):
        """Registers an arbitrary input/output pair.

        Args:
            inpath: an input path
            outpath: an output path
        """
        self._inpaths.append(inpath)
        self._outpaths.append(outpath)

    def register_paths(self, inpaths, outpaths):
        """Registers an arbitrary set of input/output pairs.

        Args:
            inpath: an input path
            outpath: an output path
        """
        for inpath, outpath in zip(inpaths, outpaths):
            self.register_path(inpath, outpath)


class GreedyFileReader(object):
    """File reader that greedily reads a configurable batch size of files
    every time it is asked to read an uncached file.

    Example usage::

        import fiftyone.core.storage as fos

        with fos.GreedyFileReader(filepaths) as f:
            for filepath in filepaths:
                file_bytes = f.read(filepath)

    Args:
        filepaths: a list of filepaths that will be read
        binary (False): whether to read the files in binary mode
        parser (None): an optional function to apply to the loaded file bytes
            prior to returning them
        use_cache (False): whether to use the locally cached versions of any
            remote files, if they exist
        batch_size (100): the number of files to read in a batch
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """

    def __init__(
        self,
        filepaths,
        binary=False,
        parser=None,
        use_cache=False,
        batch_size=100,
        progress=None,
    ):
        self.filepaths = list(filepaths)
        self.binary = binary
        self.parser = parser
        self.use_cache = use_cache
        self.batch_size = batch_size
        self.progress = progress

        self._cache = {}
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._cache.clear()

    def _read_next_batch(self):
        i = self._offset
        j = self._offset + self.batch_size
        filepaths = self.filepaths[i:j]

        if self.use_cache:
            _filepaths, _ = foc.media_cache.use_cached_paths(filepaths)
        else:
            _filepaths = filepaths

        files_bytes = read_files(
            _filepaths, binary=self.binary, progress=self.progress
        )

        self._cache.update(zip(filepaths, files_bytes))
        self._offset += self.batch_size

    def read(self, filepath):
        file_bytes = self._cache.pop(filepath, None)
        if file_bytes is None:
            self._read_next_batch()

            file_bytes = self._cache.pop(filepath, None)
            if file_bytes is None:
                if self.use_cache:
                    _filepath, _ = foc.media_cache.use_cached_path(filepath)
                else:
                    _filepath = filepath

                file_bytes = read_file(_filepath, binary=self.binary)

        if self.parser is not None:
            return self.parser(file_bytes)

        return file_bytes


def open_file(path, mode="r"):
    """Opens the given file for reading or writing.

    This function assumes that any cloud files being read/written can fit into
    RAM.

    Example usage::

        import fiftyone.core.storage as fos

        with fos.open_file("/tmp/file.txt", "w") as f:
            f.write("Hello, world!")

        with fos.open_file("s3://tmp/file.txt", "w") as f:
            f.write("Hello, world!")

        with fos.open_file("/tmp/file.txt", "r") as f:
            print(f.read())

        with fos.open_file("s3://tmp/file.txt", "r") as f:
            print(f.read())

    Args:
        path: the path
        mode ("r"): the mode. Supported values are ``("r", "rb", "w", "wb")``

    Returns:
        an open file-like object
    """
    return _open_file(path, mode)


def open_files(paths, mode="r", skip_failures=False, progress=None):
    """Opens the given files for reading or writing.

    This function assumes that all cloud files being read/written can fit into
    RAM simultaneously.

    Args:
        paths: a list of paths
        mode ("r"): the mode. Supported values are ``("r", "rb", "w", "wb")``
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead

    Returns:
        a list of open file-like objects
    """
    tasks = [(p, mode, skip_failures) for p in paths]
    return _run(_do_open_file, tasks, return_results=True, progress=progress)


def read_file(path, binary=False):
    """Reads the file into memory.

    Args:
        path: the filepath
        binary (False): whether to read the file in binary mode

    Returns:
        the file contents
    """
    return _read_file(path, binary=binary)


def read_files(paths, binary=False, skip_failures=False, progress=None):
    """Reads the specified files into memory.

    Args:
        paths: a list of filepaths
        binary (False): whether to read the files in binary mode
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead

    Returns:
        a list of file contents
    """
    tasks = [(p, binary, skip_failures) for p in paths]
    return _run(_do_read_file, tasks, return_results=True, progress=progress)


def write_file(str_or_bytes, path):
    """Writes the given string/bytes to a file.

    If a string is provided, it is encoded via ``.encode()``.

    Args:
        str_or_bytes: the string or bytes
        path: the filepath
    """
    ensure_basedir(path)
    with open_file(path, "wb") as f:
        f.write(_to_bytes(str_or_bytes))


def sep(path):
    """Returns the path separator for the given path.

    Args:
        path: the filepath

    Returns:
        the path separator
    """
    if is_local(path):
        return os.path.sep

    return "/"


def join(a, *p):
    """Joins the given path components into a single path.

    Args:
        a: the root
        *p: additional path components

    Returns:
        the joined path
    """
    if is_local(a):
        return os.path.join(a, *p)

    return posixpath.join(a, *p)


def realpath(path):
    """Converts the given path to absolute, resolving symlinks and relative
    path indicators such as ``.`` and ``..``.

    Args:
        path: the filepath

    Returns:
        the resolved path
    """
    if is_local(path):
        return os.path.realpath(path)

    return abspath(path)


def isabs(path):
    """Determines whether the given path is absolute.

    Args:
        path: the filepath

    Returns:
        True/False
    """
    if is_local(path):
        return os.path.isabs(path)

    return True


def abspath(path):
    """Converts the given path to an absolute path, resolving relative path
    indicators such as ``.`` and ``..``.

    Args:
        path: the filepath

    Returns:
        the absolute path
    """
    if is_local(path):
        return os.path.abspath(path)

    return normpath(path)


def normpath(path):
    """Normalizes the given path by converting all slashes to forward slashes
    on Unix and backslashes on Windows and removing duplicate slashes.

    Remote paths are converted to forward slashes on all platforms.

    Use this function when you need a version of ``os.path.normpath`` that
    converts ``\\`` to ``/`` on Unix.

    Args:
        path: the filepath

    Returns:
        the normalized path
    """
    if is_local(path):
        if os.name == "nt":
            return ntpath.normpath(path)

        return posixpath.normpath(path.replace("\\", "/"))

    prefix, path = split_prefix(path)

    return prefix + posixpath.normpath(path.replace("\\", "/"))


def exists(path):
    """Determines whether the given file or directory exists.

    Args:
        path: the file or directory path

    Returns:
        True/False
    """
    if is_local(path):
        return os.path.exists(path)

    client = get_client(path=path)

    if os.path.splitext(path)[1]:
        return client.is_file(path)

    return client.is_folder(path)


def isfile(path):
    """Determines whether the given file exists.

    Args:
        path: the filepath

    Returns:
        True/False
    """
    if is_local(path):
        return os.path.isfile(path)

    client = get_client(path=path)
    return client.is_file(path)


def isdir(dirpath):
    """Determines whether the given directory exists.

    Cloud "folders" are deemed to exist only if they are non-empty.

    Args:
        dirpath: the directory path

    Returns:
        True/False
    """
    if is_local(dirpath):
        return os.path.isdir(dirpath)

    client = get_client(path=dirpath)
    return client.is_folder(dirpath)


def make_archive(dirpath, archive_path, cleanup=False):
    """Makes an archive containing the given directory.

    Supported formats include ``.zip``, ``.tar``, ``.tar.gz``, ``.tgz``,
    ``.tar.bz`` and ``.tbz``.

    Args:
        dirpath: the directory to archive
        archive_path: the archive path to write
        cleanup (False): whether to delete the directory after archiving it
    """
    with LocalDir(dirpath, "r", type_str=None) as local_dir:
        with LocalFile(archive_path, "w") as local_path:
            logger.info("Making archive...")
            etau.make_archive(local_dir, local_path)

    if cleanup:
        delete_dir(dirpath)


def extract_archive(archive_path, outdir=None, cleanup=False):
    """Extracts the contents of an archive.

    The following formats are guaranteed to work:
    ``.zip``, ``.tar``, ``.tar.gz``, ``.tgz``, ``.tar.bz``, ``.tbz``.

    If an archive *not* in the above list is found, extraction will be
    attempted via the ``patool`` package, which supports many formats but may
    require that additional system packages be installed.

    Args:
        archive_path: the archive path
        outdir (None): the directory into which to extract the archive. By
            default, the directory containing the archive is used
        cleanup (False): whether to delete the archive after extraction
    """
    if outdir is None:
        outdir = os.path.dirname(archive_path) or "."

    with LocalFile(archive_path, "r") as local_path:
        with LocalDir(outdir, "w", type_str=None) as local_dir:
            logger.info("Extracting archive...")
            etau.extract_archive(local_path, outdir=local_dir)

    if cleanup:
        delete_file(archive_path)


def ensure_empty_dir(dirpath, cleanup=False):
    """Ensures that the given directory exists and is empty.

    Args:
        dirpath: the directory path
        cleanup (False): whether to delete any existing directory contents

    Raises:
        ValueError: if the directory is not empty and ``cleanup`` is False
    """
    if is_local(dirpath):
        etau.ensure_empty_dir(dirpath, cleanup=cleanup)
        return

    client = get_client(path=dirpath)

    if cleanup:
        client.delete_folder(dirpath)
    elif client.list_files_in_folder(dirpath):
        raise ValueError("'%s' is not empty" % dirpath)


def ensure_basedir(path):
    """Makes the base directory of the given path, if necessary.

    Args:
        path: the filepath
    """
    if is_local(path):
        etau.ensure_basedir(path)


def ensure_dir(dirpath):
    """Makes the given directory, if necessary.

    Args:
        dirpath: the directory path
    """
    if is_local(dirpath):
        etau.ensure_dir(dirpath)


def load_json(path_or_str):
    """Loads JSON from the input argument.

    Args:
        path_or_str: the filepath or JSON string

    Returns:
        the loaded JSON
    """
    try:
        return json.loads(path_or_str)
    except ValueError:
        pass

    if isfile(path_or_str):
        return read_json(path_or_str)

    raise ValueError("Unable to load JSON from '%s'" % path_or_str)


def read_json(path):
    """Reads a JSON file.

    Args:
        path: the filepath

    Returns:
        the JSON data
    """
    try:
        with open_file(path, "r") as f:
            return json.load(f)
    except ValueError:
        raise ValueError("Unable to parse JSON file '%s'" % path)


def write_json(d, path, pretty_print=False):
    """Writes JSON object to file.

    Args:
        d: JSON data
        path: the filepath
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """
    s = etase.json_to_str(d, pretty_print=pretty_print)
    write_file(s, path)


def load_ndjson(path_or_str):
    """Loads NDJSON from the input argument.

    Args:
        path_or_str: the filepath or NDJSON string

    Returns:
        a list of JSON dicts
    """
    try:
        return etase.load_ndjson(path_or_str)
    except ValueError:
        pass

    if isfile(path_or_str):
        return read_ndjson(path_or_str)

    raise ValueError("Unable to load NDJSON from '%s'" % path_or_str)


def read_ndjson(path):
    """Reads an NDJSON file.

    Args:
        path: the filepath

    Returns:
        a list of JSON dicts
    """
    with open_file(path, "r") as f:
        with jsonlines.Reader(f) as r:
            return list(r.iter(skip_empty=True))


def write_ndjson(obj, path):
    """Writes the list of JSON dicts in NDJSON format.

    Args:
        obj: a list of JSON dicts
        path: the filepath
    """
    with open_file(path, "w") as f:
        with jsonlines.Writer(f) as w:
            w.write_all(obj)


def read_yaml(path):
    """Reads a YAML file.

    Args:
        path: the filepath

    Returns:
        a list of JSON dicts
    """
    with open_file(path, "r") as f:
        return yaml.safe_load(f)


def write_yaml(obj, path, **kwargs):
    """Writes the object to a YAML file.

    Args:
        obj: a Python object
        path: the filepath
        **kwargs: optional arguments for ``yaml.dump(..., **kwargs)``
    """
    with open_file(path, "w") as f:
        return yaml.dump(obj, stream=f, **kwargs)


def list_files(
    dirpath,
    abs_paths=False,
    recursive=False,
    include_hidden_files=False,
    return_metadata=False,
    sort=True,
):
    """Lists the files in the given directory.

    If the directory does not exist, an empty list is returned.

    Args:
        dirpath: the path to the directory to list
        abs_paths (False): whether to return the absolute paths to the files
        recursive (False): whether to recursively traverse subdirectories
        include_hidden_files (False): whether to include dot files
        return_metadata (False): whether to return metadata dicts for each file
            instead of filepaths
        sort (True): whether to sort the list of files

    Returns:
        a list of filepaths or metadata dicts
    """
    if is_local(dirpath):
        if not os.path.isdir(dirpath):
            return []

        filepaths = etau.list_files(
            dirpath,
            abs_paths=abs_paths,
            recursive=recursive,
            include_hidden_files=include_hidden_files,
            sort=sort,
        )

        if not return_metadata:
            return filepaths

        metadata = []
        for filepath in filepaths:
            if abs_paths:
                fp = filepath
            else:
                fp = os.path.join(dirpath, filepath)

            m = _get_local_metadata(fp)
            m["filepath"] = filepath
            metadata.append(m)

        return metadata

    client = get_client(path=dirpath)

    filepaths = client.list_files_in_folder(
        dirpath,
        recursive=recursive,
        return_metadata=return_metadata,
    )

    if not return_metadata:
        if not abs_paths:
            filepaths = [os.path.relpath(f, dirpath) for f in filepaths]

        if not include_hidden_files:
            filepaths = [
                f for f in filepaths if not os.path.basename(f).startswith(".")
            ]

        if sort:
            filepaths = sorted(filepaths)

        return filepaths

    prefix = split_prefix(dirpath)[0]
    metadata = filepaths
    for m in metadata:
        filepath = prefix + m["bucket"] + "/" + m["object_name"]
        if not abs_paths:
            filepath = os.path.relpath(filepath, dirpath)

        m["filepath"] = filepath

    if not include_hidden_files:
        metadata = [
            m
            for m in metadata
            if not os.path.basename(m["filepath"]).startswith(".")
        ]

    if sort:
        metadata = sorted(metadata, key=lambda m: m["filepath"])

    return metadata


def _get_local_metadata(filepath):
    s = os.stat(filepath)
    return {
        "name": os.path.basename(filepath),
        "size": s.st_size,
        "last_modified": datetime.fromtimestamp(s.st_mtime),
    }


def list_subdirs(dirpath, abs_paths=False, recursive=False):
    """Lists the subdirectories in the given directory, sorted alphabetically
    and excluding hidden directories.

    Args:
        dirpath: the path to the directory to list
        abs_paths (False): whether to return absolute paths
        recursive (False): whether to recursively traverse subdirectories

    Returns:
        a list of subdirectories
    """
    if is_local(dirpath):
        return etau.list_subdirs(
            dirpath, abs_paths=abs_paths, recursive=recursive
        )

    if _is_root(dirpath):
        fs = get_file_system(dirpath)
        buckets = list_buckets(fs, abs_paths=True)

        if recursive:
            dirs = list(
                itertools.chain.from_iterable(
                    list_subdirs(b, abs_paths=True, recursive=True)
                    for b in buckets
                )
            )
        else:
            dirs = buckets

        if not abs_paths:
            dirs = [_split_prefix(fs, d)[1] for d in dirs]

        return dirs

    if recursive:
        filepaths = list_files(dirpath, recursive=True)
        dirs = {os.path.dirname(p) for p in filepaths}
    else:
        client = get_client(path=dirpath)
        dirs = client.list_subfolders(dirpath)
        dirs = [os.path.relpath(d, dirpath) for d in dirs]

    dirs = sorted(d for d in dirs if d and not d.startswith("."))

    if abs_paths:
        dirs = [join(dirpath, d) for d in dirs]

    return dirs


def _is_root(path):
    fs = get_file_system(path)

    if fs == FileSystem.LOCAL:
        return path == os.path.abspath(os.sep)

    if fs == FileSystem.S3:
        return path == S3_PREFIX

    if fs == FileSystem.GCS:
        return path == GCS_PREFIX

    if fs == FileSystem.AZURE:
        return any(path in prefixes for prefixes in azure_prefixes)

    if fs == FileSystem.MINIO:
        return any(path in prefixes for prefixes in minio_prefixes)

    return False


def list_buckets(fs, abs_paths=False):
    """Lists the available buckets in the given file system.

    For local file systems, this method returns subdirectories of ``/``(or the
    current drive on Windows).

    Args:
        fs: a :class:`FileSystem` value
        abs_paths (False): whether to return absolute paths

    Returns:
        a list of buckets
    """
    _refresh_managed_credentials_if_necessary()

    if fs == FileSystem.LOCAL:
        root = os.path.abspath(os.sep)
        return etau.list_subdirs(root, abs_paths=abs_paths, recursive=False)

    if fs not in _FILE_SYSTEMS_WITH_BUCKETS:
        raise ValueError("Unsupported file system '%s'" % fs)

    buckets = set()

    # Always include buckets with specific credentials
    # Note: `managed_buckets` may contain prefixed bucket names like
    # 's3://voxel51-test' or names-only like 'voxel51-test'
    managed_buckets = _get_buckets_with_managed_credentials(fs)
    if managed_buckets:
        if abs_paths:
            buckets.update(managed_buckets)
        else:
            buckets.update(_get_bucket_name(b) for b in managed_buckets)

    # Also include any buckets accessible by default credentials
    try:
        client = get_client(fs=fs)
    except:
        client = None

    default_buckets, prefix = _list_buckets(fs, client)
    if default_buckets:
        buckets.update(default_buckets)

    if abs_paths and prefix:
        buckets = [prefix + b if "/" not in b else b for b in buckets]

    return sorted(buckets)


def _list_buckets(fs, client):
    prefix = None

    buckets = set()
    if fs == FileSystem.S3:
        if client is not None:
            resp = client._client.list_buckets()
            buckets = set(r["Name"] for r in resp.get("Buckets", []))

        prefix = S3_PREFIX
    elif fs == FileSystem.GCS:
        if client is not None:
            buckets = set(b.name for b in client._client.list_buckets())

        prefix = GCS_PREFIX
    elif fs == FileSystem.AZURE:
        if client is not None:
            buckets = set(c["name"] for c in client._client.list_containers())

        if azure_prefixes:
            alias_prefix, endpoint_prefix = sorted(azure_prefixes)[0]
            prefix = alias_prefix or endpoint_prefix
    elif fs == FileSystem.MINIO:
        if client is not None:
            resp = client._client.list_buckets()
            buckets = set(r["Name"] for r in resp.get("Buckets", []))

        if minio_prefixes:
            alias_prefix, endpoint_prefix = sorted(minio_prefixes)[0]
            prefix = alias_prefix or endpoint_prefix

    return buckets, prefix


def get_glob_matches(glob_patt):
    """Returns a list of file paths matching the given glob pattern.

    The matches are returned in sorted order.

    Args:
        glob_patt: a glob pattern like ``/path/to/files-*.jpg`` or
            ``s3://path/to/files-*-*.jpg``

    Returns:
        a list of file paths
    """
    if is_local(glob_patt):
        return etau.get_glob_matches(glob_patt)

    root, found_special = get_glob_root(glob_patt)

    if not found_special:
        return [glob_patt]

    client = get_client(path=root)

    filepaths = client.list_files_in_folder(root, recursive=True)
    return sorted(
        glob.globfilter(
            filepaths, glob_patt, flags=glob.GLOBSTAR | glob.FORCEUNIX
        )
    )


def get_glob_root(glob_patt):
    """Finds the root directory of the given glob pattern, i.e., the deepest
    subdirectory that contains no glob characters.

    Args:
        glob_patt: a glob pattern like ``/path/to/files-*.jpg`` or
            ``s3://path/to/files-*-*.jpg``

    Returns:
        a tuple of:

        -   the root
        -   True/False whether the pattern contains any special characters
    """
    special_chars = "*?[]"

    # Remove escapes around special characters
    replacers = [("[%s]" % s, s) for s in special_chars]
    glob_patt = etau.replace_strings(glob_patt, replacers)

    # @todo optimization: don't split on specials that were previously escaped,
    # as this could cause much more recursive listing than necessary
    split_patt = "|".join(map(re.escape, special_chars))
    root = re.split(split_patt, glob_patt, 1)[0]

    found_special = root != glob_patt
    root = os.path.dirname(root)

    return root, found_special


def copy_file(inpath, outpath, use_cache=False):
    """Copies the input file to the output location.

    Args:
        inpath: the input path
        outpath: the output path
        use_cache (False): whether to use the locally cached version of a
            remote input file, if it exists
    """
    _copy_file(inpath, outpath, use_cache=use_cache)


def copy_files(
    inpaths,
    outpaths,
    skip_failures=False,
    use_cache=False,
    progress=None,
):
    """Copies the files to the given locations.

    Args:
        inpaths: a list of input paths
        outpaths: a list of output paths
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        use_cache (False): whether to use the locally cached versions of any
            remote input files, if they exist
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    _copy_files(
        inpaths,
        outpaths,
        skip_failures=skip_failures,
        use_cache=use_cache,
        progress=progress,
    )


def copy_dir(
    indir,
    outdir,
    overwrite=True,
    skip_failures=False,
    use_cache=False,
    progress=None,
):
    """Copies the input directory to the output directory.

    Args:
        indir: the input directory
        outdir: the output directory
        overwrite (True): whether to delete an existing output directory (True)
            or merge its contents (False)
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        use_cache (False): whether to use the locally cached versions of any
            remote input files, if they exist
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    if overwrite and isdir(outdir):
        delete_dir(outdir)

    files = list_files(
        indir, include_hidden_files=True, recursive=True, sort=False
    )
    inpaths = [join(indir, f) for f in files]
    outpaths = [join(outdir, f) for f in files]
    copy_files(
        inpaths,
        outpaths,
        skip_failures=skip_failures,
        use_cache=use_cache,
        progress=progress,
    )


def move_file(inpath, outpath):
    """Moves the given file to a new location.

    Args:
        inpath: the input path
        outpath: the output path
    """
    _copy_file(inpath, outpath, cleanup=True)


def move_files(inpaths, outpaths, skip_failures=False, progress=None):
    """Moves the files to the given locations.

    Args:
        inpaths: a list of input paths
        outpaths: a list of output paths
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    tasks = [(i, o, skip_failures) for i, o in zip(inpaths, outpaths)]
    _run(_do_move_file, tasks, return_results=False, progress=progress)


def move_dir(
    indir, outdir, overwrite=True, skip_failures=False, progress=None
):
    """Moves the contents of the given directory into the given output
    directory.

    Args:
        indir: the input directory
        outdir: the output directory
        overwrite (True): whether to delete an existing output directory (True)
            or merge its contents (False)
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    if overwrite and isdir(outdir):
        delete_dir(outdir)

    if overwrite and is_local(indir) and is_local(outdir):
        etau.ensure_basedir(outdir)
        shutil.move(indir, outdir)
        return

    files = list_files(
        indir, include_hidden_files=True, recursive=True, sort=False
    )
    inpaths = [join(indir, f) for f in files]
    outpaths = [join(outdir, f) for f in files]
    move_files(
        inpaths, outpaths, skip_failures=skip_failures, progress=progress
    )


def delete_file(path):
    """Deletes the file at the given path.

    For local paths, any empty directories are also recursively deleted from
    the resulting directory tree.

    Args:
        path: the filepath
    """
    _delete_file(path)


def delete_files(paths, skip_failures=False, progress=None):
    """Deletes the files from the given locations.

    For local paths, any empty directories are also recursively deleted from
    the resulting directory tree.

    Args:
        paths: a list of paths
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    tasks = [(p, skip_failures) for p in paths]
    _run(_do_delete_file, tasks, return_results=False, progress=progress)


def delete_dir(dirpath):
    """Deletes the given directory and recursively deletes any empty
    directories from the resulting directory tree.

    Args:
        dirpath: the directory path
    """
    if is_local(dirpath):
        etau.delete_dir(dirpath)
        return

    client = get_client(path=dirpath)
    client.delete_folder(dirpath)


def upload_media(
    sample_collection,
    remote_dir,
    rel_dir=None,
    media_field="filepath",
    update_filepaths=False,
    cache=False,
    overwrite=False,
    skip_failures=False,
    progress=None,
):
    """Uploads the source media files for the given collection to the given
    remote directory.

    Providing a ``rel_dir`` enables writing nested subfolders within
    ``remote_dir`` matching the structure of the input collection's media. By
    default, the files are written directly to ``remote_dir`` using their
    basenames.

    Args:
        sample_collection: a
            :class:`fiftyone.core.collections.SampleCollection`
        remote_dir: a remote "folder" into which to upload
        rel_dir (None): an optional relative directory to strip from each
            filepath when constructing the corresponding remote path
        media_field ("filepath"): the field containing the media paths
        update_filepaths (False): whether to update the ``media_field`` of each
            sample in the collection to its remote path
        cache (False): whether to store the uploaded media in your local media
            cache. The supported values are:

            -   ``False`` (default): do not cache the media
            -   ``True`` or ``"copy"``: copy the media into your local cache
            -   ``"move"``: move the media into your local cache
        overwrite (False): whether to overwrite (True) or skip (False) existing
            remote files
        skip_failures (False): whether to gracefully continue without raising
            an error if an operation fails
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead

    Returns:
        the list of remote paths
    """
    if sample_collection.media_type == fom.GROUP:
        sample_collection = sample_collection.select_group_slices(
            _allow_mixed=True
        )

    contains_3d = sample_collection._contains_media_type(fom.THREE_D)
    media_field = sample_collection._resolve_media_field(media_field)
    filepaths = sample_collection.values(media_field)

    filename_maker = fou.UniqueFilenameMaker(
        output_dir=remote_dir,
        rel_dir=rel_dir,
        ignore_existing=True,
    )

    paths_map = {}

    for filepath in filepaths:
        if filepath not in paths_map:
            paths_map[filepath] = filename_maker.get_output_path(filepath)

    remote_paths = [paths_map[f] for f in filepaths]

    if contains_3d:
        _update_scene_asset_paths(paths_map, filename_maker)

    if not overwrite:
        client = get_client(path=remote_dir)
        existing = set(client.list_files_in_folder(remote_dir, recursive=True))

        paths_map = {f: r for f, r in paths_map.items() if r not in existing}

    if paths_map:
        inpaths, outpaths = zip(*paths_map.items())
        _copy_files(
            inpaths,
            outpaths,
            skip_failures=skip_failures,
            cache=cache,
            progress=progress,
        )

    if update_filepaths:
        sample_collection.set_values(media_field, remote_paths)

    return remote_paths


def _update_scene_asset_paths(paths_map, filename_maker):
    scene_paths = [p for p in paths_map.keys() if p.endswith(".fo3d")]
    if not scene_paths:
        return

    scene_rewrite_paths = defaultdict(dict)
    asset_map = fou3d.get_scene_asset_paths(scene_paths, skip_failures=True)
    for scene_path, asset_paths in asset_map.items():
        in_scene_dir = os.path.dirname(scene_path)
        out_scene_dir = os.path.dirname(paths_map[scene_path])

        for asset_path in asset_paths:
            abs_asset_path = asset_path
            if not isabs(asset_path):
                abs_asset_path = abspath(join(in_scene_dir, asset_path))

            out_asset_path = filename_maker.get_output_path(abs_asset_path)

            if abs_asset_path not in paths_map:
                paths_map[abs_asset_path] = out_asset_path

            # By convention, we always write *relative* asset paths
            out_rel_path = os.path.relpath(out_asset_path, out_scene_dir)
            if asset_path != out_rel_path:
                scene_rewrite_paths[scene_path][asset_path] = out_rel_path

    if not scene_rewrite_paths:
        return

    # Update asset paths in 3D scenes and write those files into place
    tasks = [
        (scene_path, paths_map[scene_path], asset_rewrite_paths)
        for scene_path, asset_rewrite_paths in scene_rewrite_paths.items()
    ]
    run(_update_scene_asset_paths_and_write, tasks)

    # Remove scenes we already wrote so we don't overwrite them later
    for scene_path in scene_rewrite_paths.keys():
        paths_map.pop(scene_path)


def _update_scene_asset_paths_and_write(task):
    in_scene_path, out_scene_path, asset_rewrite_paths = task
    scene = fo3d.Scene.from_fo3d(in_scene_path)

    scene.update_asset_paths(asset_rewrite_paths)
    scene.write(out_scene_path)


def run(fcn, tasks, return_results=True, num_workers=None, progress=None):
    """Applies the given function to each element of the given tasks.

    Args:
        fcn: a function that accepts a single argument
        tasks: an iterable of function arguments
        return_results (True): whether to return the function results
        num_workers (None): a suggested number of threads to use
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead

    Returns:
        the list of function outputs, or None if ``return_results == False``
    """
    return _run(
        fcn,
        tasks,
        return_results=return_results,
        num_workers=num_workers,
        progress=progress,
    )


def _get_client(fs=None, path=None, credentials_path=None):
    # Client creation may not be thread-safe, so we lock for safety
    # https://stackoverflow.com/a/61943955/16823653
    with client_lock:
        return _do_get_client(
            fs=fs, path=path, credentials_path=credentials_path
        )


def _do_get_client(fs=None, path=None, credentials_path=None):
    _refresh_managed_credentials_if_necessary()

    if path is not None:
        fs = get_file_system(path)
    elif fs is None:
        raise ValueError("You must provide either a file system or a path")

    if credentials_path is not None:
        return _get_path_client(fs, credentials_path)

    if path is not None:
        bucket = _get_bucket(fs, path)
    else:
        bucket = None

    if not bucket:
        return _get_default_client(fs)

    if _has_managed_credentials(fs, bucket):
        return _get_bucket_client(fs, bucket)

    if fs in _FILE_SYSTEMS_WITH_REGIONAL_CLIENTS:
        return _get_regional_client(fs, bucket)

    return _get_default_client(fs)


def _get_bucket_client(fs, bucket):
    if fs not in bucket_clients:
        bucket_clients[fs] = {}

    client = bucket_clients[fs].get(bucket, None)
    if client is None:
        if fs in _FILE_SYSTEMS_WITH_REGIONAL_CLIENTS:
            region = _get_region(fs, bucket)
        else:
            region = None

        try:
            client = _make_client(fs, bucket=bucket, region=region)
        except Exception as e:
            client = e

        bucket_clients[fs][bucket] = client

        if fs in _FILE_SYSTEMS_WITH_ALIASES:
            _bucket = _swap_prefix(fs, bucket)
            bucket_clients[fs][_bucket] = client

    if isinstance(client, Exception):
        raise client

    return client


def _get_regional_client(fs, bucket):
    region = _get_region(fs, bucket)

    if region == _UNKNOWN_REGION:
        return _get_default_client(fs)

    if fs not in region_clients:
        region_clients[fs] = {}

    client = region_clients[fs].get(region, None)
    if client is None:
        try:
            client = _make_client(fs, bucket=bucket, region=region)
        except Exception as e:
            client = e

        region_clients[fs][region] = client

    if isinstance(client, Exception):
        raise client

    return client


def _get_path_client(fs, credentials_path):
    if fs not in path_clients:
        path_clients[fs] = {}

    client = path_clients[fs].get(credentials_path, None)
    if client is None:
        try:
            client = _make_client(fs, credentials_path=credentials_path)
        except Exception as e:
            client = e

        path_clients[fs][credentials_path] = client

    if isinstance(client, Exception):
        raise client

    return client


def _get_default_client(fs):
    client = default_clients.get(fs, None)
    if client is None:
        try:
            client = _make_client(fs)
        except Exception as e:
            client = e

        default_clients[fs] = client

    if isinstance(client, Exception):
        raise client

    return client


def _get_region(fs, bucket):
    if fs not in bucket_regions:
        bucket_regions[fs] = {}

    region = bucket_regions[fs].get(bucket, None)
    if region is None:
        region = _do_get_region(fs, bucket)

        bucket_regions[fs][bucket] = region

    return region


def _do_get_region(fs, bucket):
    if _has_managed_credentials(fs, bucket):
        # We make a new client here and *don't* cache it because the cached
        # client will need to have region information stored on it, which we
        # don't have yet
        client = _make_client(fs, bucket=bucket)
    else:
        client = _get_default_client(fs)

    bucket_name = _get_bucket_name(bucket)

    try:
        # HeadBucket is the AWS recommended way to determine a bucket's region
        # It requires `s3:ListBucket` permsision
        resp = client._client.head_bucket(Bucket=bucket_name)
        headers = resp["ResponseMetadata"]["HTTPHeaders"]
        return headers.get("x-amz-bucket-region", "us-east-1")
    except Exception as e1:
        try:
            # Fallback to GetBucketLocation, which requires
            # `s3:GetBucketLocation` permission but does not support
            # multi-account credentials
            resp = client._client.get_bucket_location(Bucket=bucket_name)
            return resp["LocationConstraint"] or "us-east-1"
        except Exception as e2:
            logger.warning(
                "Failed to determine file system '%s' bucket '%s' location. "
                "HeadBucket: %s. GetBucketLocation: %s",
                fs,
                bucket_name,
                e1,
                e2,
            )

            return _UNKNOWN_REGION


def _make_client(
    fs,
    bucket=None,
    region=None,
    credentials_path=None,
    num_workers=None,
):
    if region is not None and fs not in _FILE_SYSTEMS_WITH_REGIONAL_CLIENTS:
        region = None
        logger.debug("Ignoring region for non-regional file system '%s'", fs)

    if num_workers is None:
        num_workers = fo.media_cache_config.num_workers

    profile = None
    kwargs = (fo.media_cache_config.extra_client_kwargs or {}).get(fs, {})

    if num_workers is not None and num_workers > 10:
        kwargs["max_pool_connections"] = num_workers

    if fs == FileSystem.S3:
        if credentials_path is None:
            credentials_path, profile = _load_s3_credentials(bucket=bucket)

        return _make_s3_client(credentials_path, profile, region, **kwargs)

    if fs == FileSystem.GCS:
        if credentials_path is None:
            credentials_path = _load_gcs_credentials(bucket=bucket)

        return _make_gcs_client(credentials_path, **kwargs)

    if fs == FileSystem.AZURE:
        if credentials_path is None:
            credentials_path, profile = _load_azure_credentials(bucket=bucket)

        return _make_azure_client(credentials_path, profile, **kwargs)

    if fs == FileSystem.MINIO:
        if credentials_path is None:
            credentials_path, profile = _load_minio_credentials(bucket=bucket)

        return _make_minio_client(credentials_path, profile, region, **kwargs)

    if fs == FileSystem.HTTP:
        return HTTPStorageClient(**kwargs)

    raise ValueError("Unsupported file system '%s'" % fs)


def _refresh_managed_credentials_if_necessary():
    if creds_manager is None:
        return

    if creds_manager.is_expired:
        init_storage()


def _get_buckets_with_managed_credentials(fs):
    if creds_manager is None:
        return None

    buckets = set()

    # Buckets with exact credentials
    for bucket in creds_manager.get_buckets_with_credentials(fs):
        buckets.add(bucket)

    # Buckets matching patterned credentials
    for regex, patt, creds_path in creds_manager.get_patterned_credentials(fs):
        try:
            client = _get_client(fs, credentials_path=creds_path)
        except:
            client = None

        if client is not None:
            path_buckets, _ = _list_buckets(fs, client)

            # Handle regexes that included prefix like 's3://voxel51-*' or
            # 'https://voxel51.blob.core.windows.net/voxel51-*'
            if "/" in patt:
                prefix, _ = patt.rsplit("/", 1)
                path_buckets = [prefix + "/" + b for b in path_buckets]

            buckets.update(b for b in path_buckets if regex.fullmatch(b))

    return buckets


def _get_file_systems_with_managed_credentials():
    if creds_manager is None:
        return None

    return creds_manager.get_file_systems_with_credentials()


def _has_managed_credentials(fs, bucket):
    if creds_manager is None:
        return False

    # Check prefix + bucket
    has_creds = creds_manager.has_bucket_credentials(fs, bucket)
    if has_creds:
        return True

    # Swap alias <> endpoint and check again, if applicable
    if fs in _FILE_SYSTEMS_WITH_ALIASES:
        _bucket = _swap_prefix(fs, bucket)
        has_creds = creds_manager.has_bucket_credentials(fs, _bucket)
        if has_creds:
            return True

    # Check bucket name-only
    bucket_name = _get_bucket_name(bucket)
    return creds_manager.has_bucket_credentials(fs, bucket_name)


def _get_managed_credentials(fs, bucket=None):
    if creds_manager is None:
        return None

    if bucket is None:
        return creds_manager.get_credentials(fs)

    # Check prefix + bucket
    if creds_manager.has_bucket_credentials(fs, bucket):
        return creds_manager.get_credentials(fs, bucket=bucket)

    # Swap alias <> endpoint and check again, if applicable
    if fs in _FILE_SYSTEMS_WITH_ALIASES:
        _bucket = _swap_prefix(fs, bucket)
        if creds_manager.has_bucket_credentials(fs, _bucket):
            return creds_manager.get_credentials(fs, bucket=_bucket)

    # Check bucket name-only
    bucket_name = _get_bucket_name(bucket)
    return creds_manager.get_credentials(fs, bucket=bucket_name)


def _load_s3_credentials(bucket=None):
    credentials_path = _get_managed_credentials(FileSystem.S3, bucket=bucket)
    profile = None

    if credentials_path:
        logger.debug("Loaded S3 credentials from database")
    else:
        credentials_path = fo.media_cache_config.aws_config_file
        profile = fo.media_cache_config.aws_profile
        logger.debug("Loaded S3 credentials from environment")

    return credentials_path, profile


def _make_s3_client(credentials_path, profile, region, **client_kwargs):
    credentials, _ = S3StorageClient.load_credentials(
        credentials_path=credentials_path, profile=profile
    )
    if region is not None:
        if credentials is None:
            credentials = {}

        credentials["region"] = region

    return S3StorageClient(credentials=credentials, **client_kwargs)


def _load_gcs_credentials(bucket=None):
    credentials_path = _get_managed_credentials(FileSystem.GCS, bucket=bucket)

    if credentials_path:
        logger.debug("Loaded GCP credentials from database")
    else:
        credentials_path = fo.media_cache_config.google_application_credentials
        logger.debug("Loaded GCP credentials from environment")

    return credentials_path


def _make_gcs_client(credentials_path, **client_kwargs):
    credentials, _ = GoogleCloudStorageClient.load_credentials(
        credentials_path=credentials_path
    )
    return GoogleCloudStorageClient(credentials=credentials, **client_kwargs)


def _load_azure_credentials(bucket=None):
    credentials_path = _get_managed_credentials(
        FileSystem.AZURE, bucket=bucket
    )
    profile = None

    if credentials_path:
        logger.debug("Loaded Azure credentials from database")
    else:
        credentials_path = fo.media_cache_config.azure_credentials_file
        profile = fo.media_cache_config.azure_profile
        logger.debug("Loaded Azure credentials from environment")

    return credentials_path, profile


def _make_azure_client(credentials_path, profile, **client_kwargs):
    credentials, _ = AzureStorageClient.load_credentials(
        credentials_path=credentials_path, profile=profile
    )
    return AzureStorageClient(credentials=credentials, **client_kwargs)


def _load_minio_credentials(bucket=None):
    credentials_path = _get_managed_credentials(
        FileSystem.MINIO, bucket=bucket
    )
    profile = None

    if credentials_path:
        logger.debug("Loaded MinIO credentials from database")
    else:
        credentials_path = fo.media_cache_config.minio_config_file
        profile = fo.media_cache_config.minio_profile
        logger.debug("Loaded MinIO credentials from environment")

    return credentials_path, profile


def _make_minio_client(credentials_path, profile, region, **client_kwargs):
    credentials, _ = MinIOStorageClient.load_credentials(
        credentials_path=credentials_path, profile=profile
    )
    if region is not None:
        if credentials is None:
            credentials = {}

        credentials["region"] = region

    return MinIOStorageClient(credentials=credentials, **client_kwargs)


def _copy_files(
    inpaths,
    outpaths,
    skip_failures=False,
    cache=False,
    use_cache=False,
    progress=None,
):
    supported_cache_values = ("copy", "move", True, False)
    if cache not in supported_cache_values:
        raise ValueError(
            "Unsupported cache parameter '%s'. The supported values are %s"
            % (cache, supported_cache_values)
        )

    if cache is True:
        cache = "copy"

    tasks = [
        (i, o, skip_failures, cache, use_cache)
        for i, o in zip(inpaths, outpaths)
    ]
    _run(_do_copy_file, tasks, return_results=False, progress=progress)


def _run(fcn, tasks, return_results=True, num_workers=None, progress=None):
    try:
        num_tasks = len(tasks)
    except:
        num_tasks = None

    if num_tasks == 0:
        return [] if return_results else None

    num_workers = fou.recommend_thread_pool_workers(num_workers)
    kwargs = dict(total=num_tasks, iters_str="files", progress=progress)

    if num_workers <= 1:
        with fou.ProgressBar(**kwargs) as pb:
            if return_results:
                results = [fcn(task) for task in pb(tasks)]
            else:
                for task in pb(tasks):
                    fcn(task)
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(**kwargs) as pb:
                if return_results:
                    results = list(pb(pool.imap(fcn, tasks)))
                else:
                    for _ in pb(pool.imap_unordered(fcn, tasks)):
                        pass

    if return_results:
        return results


def _do_copy_file(arg):
    inpath, outpath, skip_failures, cache, use_cache = arg

    try:
        _copy_file(inpath, outpath, use_cache=use_cache)
        if cache:
            # Implicitly assumes outpath is the remote path
            foc.media_cache.add(
                [inpath], [outpath], method=cache, overwrite=True
            )
    except Exception as e:
        if not skip_failures:
            raise

        if skip_failures != "ignore":
            logger.warning(e)


def _do_move_file(arg):
    inpath, outpath, skip_failures = arg

    try:
        _copy_file(inpath, outpath, cleanup=True)
    except Exception as e:
        if not skip_failures:
            raise

        if skip_failures != "ignore":
            logger.warning(e)


def _do_delete_file(arg):
    filepath, skip_failures = arg

    try:
        _delete_file(filepath)
    except Exception as e:
        if not skip_failures:
            raise

        if skip_failures != "ignore":
            logger.warning(e)


def _do_open_file(arg):
    filepath, mode, skip_failures = arg

    try:
        return _open_file(filepath, mode)
    except Exception as e:
        if not skip_failures:
            raise

        if skip_failures != "ignore":
            logger.warning(e)


def _open_file(path, mode):
    if is_local(path):
        return open(path, mode)

    return _OpenFile(path, mode)


class _OpenFile(object):
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode
        self._is_writing = None
        self._client = None
        self._f = None
        self._f_iter = None
        self._open()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        self._f_iter = iter(self._f)
        return self

    def __next__(self):
        return next(self._f_iter)

    def __getattr__(self, *args, **kwargs):
        return getattr(self._f, *args, **kwargs)

    def _open(self):
        client = get_client(path=self.path)
        is_writing = self.mode in ("w", "wb")

        if self.mode == "r":
            b = client.download_bytes(self.path)
            f = io.StringIO(b.decode())
        elif self.mode == "rb":
            f = io.BytesIO()
            client.download_stream(self.path, f)
        elif is_writing:
            f = _BytesIO()
        else:
            raise ValueError("Unsupported mode '%s'" % self.mode)

        f.seek(0)

        self._is_writing = is_writing
        self._client = client
        self._f = f

    def close(self):
        """Flush and close the IO object.

        This method has no effect if the file is already closed.
        """
        try:
            if self._is_writing and not self._f.closed:
                self._f.seek(0)
                self._client.upload_stream(
                    self._f,
                    self.path,
                    content_type=etau.guess_mime_type(self.path),
                )
        finally:
            self._f.close()


def _do_read_file(arg):
    filepath, binary, skip_failures = arg

    try:
        return _read_file(filepath, binary=binary)
    except Exception as e:
        if not skip_failures:
            raise

        if skip_failures != "ignore":
            logger.warning(e)


def _read_file(filepath, binary=False):
    mode = "rb" if binary else "r"
    with open_file(filepath, mode) as f:
        return f.read()


def _copy_file(inpath, outpath, use_cache=False, cleanup=False):
    if use_cache:
        inpath, local_in = foc.media_cache.use_cached_path(inpath)
    else:
        local_in = is_local(inpath)

    local_out = is_local(outpath)

    if local_in:
        if local_out:
            # Local -> local
            etau.ensure_basedir(outpath)
            if cleanup:
                shutil.move(inpath, outpath)
            else:
                shutil.copy(inpath, outpath)
        else:
            # Local -> remote
            client = get_client(path=outpath)
            client.upload(inpath, outpath)
            if cleanup:
                os.remove(inpath)
    elif local_out:
        # Remote -> local
        client = get_client(path=inpath)
        client.download(inpath, outpath)
        if cleanup:
            client.delete(inpath)
    else:
        # Remote -> remote
        clienti = get_client(path=inpath)
        b = clienti.download_bytes(inpath)
        cliento = get_client(path=outpath)
        cliento.upload_bytes(b, outpath)
        if cleanup:
            clienti.delete(inpath)


def _delete_file(filepath):
    if is_local(filepath):
        etau.delete_file(filepath)
        return

    client = get_client(path=filepath)
    client.delete(filepath)


class _BytesIO(io.BytesIO):
    def write(self, str_or_bytes):
        super().write(_to_bytes(str_or_bytes))


def _to_bytes(val, encoding="utf-8"):
    b = val.encode(encoding) if isinstance(val, str) else val
    if not isinstance(b, bytes):
        raise TypeError("Failed to convert %s to bytes" % type(b))

    return b


def _parse_progress(progress):
    if progress is None:
        return fo.config.show_progress_bars

    return progress
