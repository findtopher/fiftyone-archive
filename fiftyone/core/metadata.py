"""
Metadata stored in dataset samples.

| Copyright 2017-2024, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
from collections import defaultdict
import itertools
import json
import logging
import multiprocessing.dummy
import os

import backoff
from PIL import Image
import requests

import eta.core.utils as etau
import eta.core.video as etav

import fiftyone as fo
import fiftyone.core.cache as foc
from fiftyone.core.config import HTTPRetryConfig
import fiftyone.core.fields as fof
import fiftyone.core.media as fom
from fiftyone.core.odm import DynamicEmbeddedDocument
import fiftyone.core.storage as fos
import fiftyone.core.threed as fo3d
import fiftyone.core.utils as fou


logger = logging.getLogger(__name__)


class Metadata(DynamicEmbeddedDocument):
    """Base class for storing metadata about generic samples.

    Args:
        size_bytes (None): the size of the media, in bytes
        mime_type (None): the MIME type of the media
    """

    size_bytes = fof.IntField()
    mime_type = fof.StringField()

    @classmethod
    def build_for(cls, path, mime_type=None):
        """Builds a :class:`Metadata` object for the given file.

        Args:
            path: the path to the data
            mime_type (None): the MIME type of the file. If not provided, it
                will be guessed

        Returns:
            a :class:`Metadata`
        """
        path, is_local = fo.media_cache.use_cached_path(path)

        if is_local:
            return cls._build_for_local(path, mime_type=mime_type)

        url = fos.get_url(path)
        return cls._build_for_url(url, mime_type=mime_type)

    @classmethod
    def _build_for_local(cls, filepath, mime_type=None):
        if mime_type is None:
            mime_type = etau.guess_mime_type(filepath)

        size_bytes = os.path.getsize(filepath)

        return cls(size_bytes=size_bytes, mime_type=mime_type)

    @classmethod
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        factor=HTTPRetryConfig.FACTOR,
        max_tries=HTTPRetryConfig.MAX_TRIES,
        giveup=lambda e: e.response.status_code
        not in HTTPRetryConfig.RETRY_CODES,
        logger=None,
    )
    def _build_for_url(cls, url, mime_type=None):
        if mime_type is None:
            mime_type = etau.guess_mime_type(url)

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            size_bytes = int(r.headers["Content-Length"])

        return cls(size_bytes=size_bytes, mime_type=mime_type)


class ImageMetadata(Metadata):
    """Class for storing metadata about image samples.

    Args:
        size_bytes (None): the size of the image on disk, in bytes
        mime_type (None): the MIME type of the image
        width (None): the width of the image, in pixels
        height (None): the height of the image, in pixels
        num_channels (None): the number of channels in the image
    """

    width = fof.IntField()
    height = fof.IntField()
    num_channels = fof.IntField()

    @classmethod
    def build_for(cls, img_or_path, mime_type=None):
        """Builds an :class:`ImageMetadata` object for the given image.

        Args:
            img_or_path: an image or the path to an image
            mime_type (None): the MIME type of the image. If not provided, it
                will be guessed

        Returns:
            an :class:`ImageMetadata`
        """
        if not etau.is_str(img_or_path):
            return cls._build_for_img(img_or_path, mime_type=mime_type)

        img_path, is_local = fo.media_cache.use_cached_path(img_or_path)

        if is_local:
            return cls._build_for_local(img_path, mime_type=mime_type)

        url = fos.get_url(img_path)
        return cls._build_for_url(url, mime_type=mime_type)

    @classmethod
    def _build_for_local(cls, path, mime_type=None):
        size_bytes = os.path.getsize(path)

        if mime_type is None:
            mime_type = etau.guess_mime_type(path)

        with open(path, "rb") as f:
            width, height, num_channels = get_image_info(f)

        return cls(
            size_bytes=size_bytes,
            mime_type=mime_type,
            width=width,
            height=height,
            num_channels=num_channels,
        )

    @classmethod
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        factor=HTTPRetryConfig.FACTOR,
        max_tries=HTTPRetryConfig.MAX_TRIES,
        giveup=lambda e: e.response.status_code
        not in HTTPRetryConfig.RETRY_CODES,
        logger=None,
    )
    def _build_for_url(cls, url, mime_type=None):
        if mime_type is None:
            mime_type = etau.guess_mime_type(url)

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            size_bytes = int(r.headers["Content-Length"])
            width, height, num_channels = get_image_info(fou.ResponseStream(r))

        return cls(
            size_bytes=size_bytes,
            mime_type=mime_type,
            width=width,
            height=height,
            num_channels=num_channels,
        )

    @classmethod
    def _build_for_img(cls, img, mime_type=None):
        size_bytes = img.nbytes
        height, width = img.shape[:2]
        try:
            num_channels = img.shape[2]
        except IndexError:
            num_channels = 1

        return cls(
            size_bytes=size_bytes,
            mime_type=mime_type,
            width=width,
            height=height,
            num_channels=num_channels,
        )


class VideoMetadata(Metadata):
    """Class for storing metadata about video samples.

    Args:
        size_bytes (None): the size of the video on disk, in bytes
        mime_type (None): the MIME type of the video
        frame_width (None): the width of the video frames, in pixels
        frame_height (None): the height of the video frames, in pixels
        frame_rate (None): the frame rate of the video
        total_frame_count (None): the total number of frames in the video
        duration (None): the duration of the video, in seconds
        encoding_str (None): the encoding string for the video
    """

    frame_width = fof.IntField()
    frame_height = fof.IntField()
    frame_rate = fof.FloatField()
    total_frame_count = fof.IntField()
    duration = fof.FloatField()
    encoding_str = fof.StringField()

    @classmethod
    def build_for(cls, video_path, mime_type=None):
        """Builds an :class:`VideoMetadata` object for the given video.

        Args:
            video_path: the path to a video
            mime_type (None): the MIME type of the image. If not provided, it
                will be guessed

        Returns:
            a :class:`VideoMetadata`
        """
        video_path, is_local = fo.media_cache.use_cached_path(video_path)

        if is_local:
            return cls._build_for_local(video_path, mime_type=mime_type)

        url = fos.get_url(video_path)
        return cls._build_for_url(url, mime_type=mime_type)

    @classmethod
    def _build_for_local(cls, video_path, mime_type=None):
        stream_info = etav.VideoStreamInfo.build_for(
            video_path, mime_type=mime_type
        )

        return cls(
            size_bytes=stream_info.size_bytes,
            mime_type=stream_info.mime_type,
            frame_width=stream_info.frame_size[0],
            frame_height=stream_info.frame_size[1],
            frame_rate=stream_info.frame_rate,
            total_frame_count=stream_info.total_frame_count,
            duration=stream_info.duration,
            encoding_str=stream_info.encoding_str,
        )

    @classmethod
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        factor=HTTPRetryConfig.FACTOR,
        max_tries=HTTPRetryConfig.MAX_TRIES,
        giveup=lambda e: e.response.status_code
        not in HTTPRetryConfig.RETRY_CODES,
        logger=None,
    )
    def _build_for_url(cls, url, mime_type=None):
        try:
            stream_info = etav.VideoStreamInfo.build_for(
                url, mime_type=mime_type
            )
        except Exception as e:
            # Something went wrong; if we get a retryable code when pinging the
            # URL, trigger a retry
            with requests.get(url, stream=True) as r:
                r.raise_for_status()

            raise e

        return cls(
            size_bytes=stream_info.size_bytes,
            mime_type=stream_info.mime_type,
            frame_width=stream_info.frame_size[0],
            frame_height=stream_info.frame_size[1],
            frame_rate=stream_info.frame_rate,
            total_frame_count=stream_info.total_frame_count,
            duration=stream_info.duration,
            encoding_str=stream_info.encoding_str,
        )


class SceneMetadata(Metadata):
    """Class for storing metadata about 3D scene samples.

    Args:
        size_bytes (None): the size of scene definition and all children
            assets on disk, in bytes
        mime_type (None): the MIME type of the scene
        asset_counts (None): dict of child asset file type to count
    """

    asset_counts = fof.DictField()

    @classmethod
    def build_for(cls, scene_path, mime_type=None, _cache=None):
        """Builds a :class:`SceneMetadata` object for the given 3D scene.

        Args:
            scene_path: a scene path
            mime_type (None): the MIME type of the scene. If not provided,
                defaults to ``application/octet-stream``

        Returns:
            a :class:`SceneMetadata`
        """
        scene_path, is_local = fo.media_cache.use_cached_path(scene_path)

        if is_local:
            return cls._build_for_local(
                scene_path, mime_type=mime_type, cache=_cache
            )

        url = fos.get_url(scene_path)
        return cls._build_for_url(
            url, scene_path, mime_type=mime_type, cache=_cache
        )

    @classmethod
    def _build_for_local(cls, scene_path, mime_type=None, cache=None):
        if mime_type is None:
            mime_type = "application/octet-stream"

        scene_size = os.path.getsize(scene_path)
        scene = fo3d.Scene.from_fo3d(scene_path)

        asset_counts, asset_size = _parse_assets(
            scene, scene_path, cache=cache
        )
        size_bytes = scene_size + asset_size

        return cls(
            size_bytes=size_bytes,
            mime_type=mime_type,
            asset_counts=asset_counts,
        )

    @classmethod
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        factor=HTTPRetryConfig.FACTOR,
        max_tries=HTTPRetryConfig.MAX_TRIES,
        giveup=lambda e: e.response.status_code
        not in HTTPRetryConfig.RETRY_CODES,
        logger=None,
    )
    def _build_for_url(cls, url, scene_path, mime_type=None, cache=None):
        if mime_type is None:
            mime_type = "application/octet-stream"

        r = requests.get(url)
        r.raise_for_status()
        scene_size = int(r.headers["Content-Length"])
        scene = fo3d.Scene._from_fo3d_dict(r.json())

        asset_counts, asset_size = _parse_assets(
            scene, scene_path, cache=cache
        )
        size_bytes = scene_size + asset_size

        return cls(
            size_bytes=size_bytes,
            mime_type=mime_type,
            asset_counts=asset_counts,
        )


def _parse_assets(scene, scene_path, cache=None):
    asset_paths = scene.get_asset_paths()

    asset_counts = defaultdict(int)
    scene_dir = os.path.dirname(scene_path)
    for i, asset_path in enumerate(asset_paths):
        if not fos.isabs(asset_path):
            asset_path = fos.abspath(fos.join(scene_dir, asset_path))
            asset_paths[i] = asset_path

        file_type = os.path.splitext(asset_path)[1][1:]
        asset_counts[file_type] += 1

    asset_size = 0

    tasks = []
    for asset_path in asset_paths:
        if cache is not None:
            metadata = cache.get(asset_path, None)
            if metadata is not None:
                asset_size += metadata.size_bytes
                continue

        tasks.append((None, asset_path, fom.MIXED, cache))

    results = []
    if len(tasks) <= 1:
        for task in tasks:
            results.append(_do_compute_metadata(task))
    else:
        num_workers = fou.recommend_thread_pool_workers(min(len(tasks), 8))
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            results.extend(pool.imap(_do_compute_metadata, tasks))

    for task, result in zip(tasks, results):
        metadata = result[1]
        asset_size += metadata.size_bytes

        if cache is not None:
            scene_path = task[1]
            cache[scene_path] = metadata

    return dict(asset_counts), asset_size


def compute_sample_metadata(sample, overwrite=False, skip_failures=False):
    """Populates the ``metadata`` field of the sample.

    Args:
        sample: a :class:`fiftyone.core.sample.Sample`
        overwrite (False): whether to overwrite existing metadata
        skip_failures (False): whether to gracefully continue without raising
            an error if metadata cannot be computed
    """
    if not overwrite and sample.metadata is not None:
        return

    sample.metadata = _compute_sample_metadata(
        sample.filepath, sample.media_type, skip_failures=skip_failures
    )
    if sample._in_db:
        sample.save()


def get_metadata_cls(media_type):
    """Get the ``metadata`` class for a media_type

    Args:
        media_type (str): a media type value

    Returns:
        a :class:`Metadata` class
    """
    if media_type == fom.IMAGE:
        return ImageMetadata
    elif media_type == fom.VIDEO:
        return VideoMetadata

    return Metadata


def compute_metadata(
    sample_collection,
    overwrite=False,
    num_workers=None,
    skip_failures=True,
    warn_failures=False,
    progress=None,
):
    """Populates the ``metadata`` field of all samples in the collection.

    Any samples with existing metadata are skipped, unless
    ``overwrite == True``.

    Args:
        sample_collection: a
            :class:`fiftyone.core.collections.SampleCollection`
        overwrite (False): whether to overwrite existing metadata
        num_workers (None): a suggested number of threads to use
        skip_failures (True): whether to gracefully continue without raising an
            error if metadata cannot be computed for a sample
        warn_failures (False): whether to log a warning if metadata cannot
            be computed for a sample
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead
    """
    if num_workers is None:
        num_workers = fo.media_cache_config.num_workers

    num_workers = fou.recommend_thread_pool_workers(num_workers)

    if sample_collection.media_type == fom.GROUP:
        sample_collection = sample_collection.select_group_slices(
            _allow_mixed=True
        )

    if num_workers <= 1:
        _compute_metadata(
            sample_collection, overwrite=overwrite, progress=progress
        )
    else:
        _compute_metadata_multi(
            sample_collection,
            num_workers,
            overwrite=overwrite,
            progress=progress,
        )

    if skip_failures and not warn_failures:
        return

    num_missing = len(sample_collection.exists("metadata", False))
    if num_missing > 0:
        msg = (
            "Failed to populate metadata on %d samples. "
            + 'Use `dataset.exists("metadata", False)` to retrieve them'
        ) % num_missing

        if skip_failures:
            logger.warning(msg)
        else:
            raise ValueError(msg)


def get_metadata(
    filepaths, num_workers=None, skip_failures=True, progress=None
):
    """Gets :class:`Metadata` instances for the given filepaths.

    Args:
        filepaths: an iterable of filepaths
        num_workers (None): the number of worker threads to use
        skip_failures (True): whether to gracefully continue without raising an
            error if metadata cannot be computed for a file
        progress (None): whether to render a progress bar (True/False), use the
            default value ``fiftyone.config.show_progress_bars`` (None), or a
            progress callback function to invoke instead

    Returns:
        a dict mapping filepaths to :class:`Metadata` instances
    """
    if num_workers is None:
        num_workers = fo.media_cache_config.num_workers

    num_workers = fou.recommend_thread_pool_workers(num_workers)

    cache = {}
    metadata = {}
    tasks = [(p, skip_failures, cache) for p in filepaths]

    if not tasks:
        return metadata

    logger.info("Getting metadata...")
    if not num_workers or num_workers <= 1:
        with fou.ProgressBar(
            total=len(tasks), iters_str="files", progress=progress
        ) as pb:
            for task in pb(tasks):
                filepath, _metadata = _do_get_metadata(task)
                metadata[filepath] = _metadata
    else:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(
                total=len(tasks), iters_str="files", progress=progress
            ) as pb:
                results = pool.imap_unordered(_do_get_metadata, tasks)
                for filepath, _metadata in pb(results):
                    metadata[filepath] = _metadata

    return metadata


def _image_has_flipped_dimensions(img):
    """Returns True if image has flipped width/height dimensions

    EXIF Orientation metadata can specify that an image be rotated or otherwise
    transposed. ``PIL.Image`` does not handle this by default so we have to
    inspect the EXIF info. See ``PIL.ImageOps.exif_transpose()`` for the basis
    of this function, except we don't actually want to transpose the image
    when we only need the dimensions.

    Tag name reference: https://exiftool.org/TagNames/EXIF.html
    PIL.ImageOps reference: https://github.com/python-pillow/Pillow/blob/main/src/PIL/ImageOps.py

    Args:
        img: a ``PIL.Image``

    Returns:
        True if image width/height should be flipped
    """
    # Value from PIL.ExifTags.Base.Orientation == 274
    #   We hard-code the value directly here so we can support older Pillow
    #   versions that don't have ExifTags.Base.
    #   It's ok because this value will never change.
    orientation_tag = 0x0112
    exif_orientation = img.getexif().get(orientation_tag)
    # 5, 6, 7, 8 --> TRANSPOSE, ROTATE_270, TRANSVERSE, ROTATE_90
    is_rotated = exif_orientation in {5, 6, 7, 8}
    return is_rotated


def get_image_info(f):
    """Retrieves the dimensions and number of channels of the given image from
    a file-like object that is streaming its contents.

    Args:
        f: a file-like object that supports ``read()``, ``seek()``, ``tell()``

    Returns:
        ``(width, height, num_channels)``
    """
    img = Image.open(f)

    # Flip the dimensions if image metadata requires us to. PIL.Image doesn't
    #   handle by default.
    if _image_has_flipped_dimensions(img):
        width, height = img.height, img.width
    else:
        width, height = img.width, img.height

    return width, height, len(img.getbands())


def _compute_metadata(
    sample_collection, overwrite=False, batch_size=1000, progress=None
):
    if not overwrite:
        sample_collection = sample_collection.exists("metadata", False)

    ids, filepaths, media_types = sample_collection.values(
        ["id", "filepath", "_media_type"],
        _allow_missing=True,
    )

    num_samples = len(ids)
    if num_samples == 0:
        return

    logger.info("Computing metadata...")

    cache = {}
    values = {}
    inputs = zip(ids, filepaths, media_types, itertools.repeat(cache))

    try:
        with fou.ProgressBar(total=num_samples, progress=progress) as pb:
            for args in pb(inputs):
                sample_id, metadata = _do_compute_metadata(args)
                values[sample_id] = metadata
                if len(values) >= batch_size:
                    sample_collection.set_values(
                        "metadata", values, key_field="id"
                    )
                    values.clear()
    finally:
        sample_collection.set_values("metadata", values, key_field="id")


def _compute_metadata_multi(
    sample_collection,
    num_workers,
    overwrite=False,
    batch_size=1000,
    progress=None,
):
    if not overwrite:
        sample_collection = sample_collection.exists("metadata", False)

    ids, filepaths, media_types = sample_collection.values(
        ["id", "filepath", "_media_type"],
        _allow_missing=True,
    )

    num_samples = len(ids)
    if num_samples == 0:
        return

    logger.info("Computing metadata...")

    cache = {}
    values = {}
    inputs = zip(ids, filepaths, media_types, itertools.repeat(cache))

    try:
        with multiprocessing.dummy.Pool(processes=num_workers) as pool:
            with fou.ProgressBar(total=num_samples, progress=progress) as pb:
                for sample_id, metadata in pb(
                    pool.imap_unordered(_do_compute_metadata, inputs)
                ):
                    values[sample_id] = metadata
                    if len(values) >= batch_size:
                        sample_collection.set_values(
                            "metadata", values, key_field="id"
                        )
                        values.clear()
    finally:
        sample_collection.set_values("metadata", values, key_field="id")


def _do_compute_metadata(args):
    sample_id, filepath, media_type, cache = args
    metadata = _compute_sample_metadata(
        filepath, media_type, skip_failures=True, cache=cache
    )
    return sample_id, metadata


def _compute_sample_metadata(
    filepath, media_type, skip_failures=False, cache=None
):
    if not skip_failures:
        return _get_metadata(filepath, media_type, cache=cache)

    try:
        return _get_metadata(filepath, media_type, cache=cache)
    except:
        return None


def _do_get_metadata(args):
    filepath, skip_failures, cache = args
    if not filepath:
        return None, None

    filepath, _ = foc.media_cache.use_cached_path(filepath)
    media_type = fom.get_media_type(filepath)

    try:
        metadata = _get_metadata(filepath, media_type, cache=cache)
    except Exception as e:
        if not skip_failures:
            raise

        metadata = None
        logger.warning(e)

    return filepath, metadata


def _get_metadata(filepath, media_type, cache=None):
    if cache is not None:
        metadata = cache.get(filepath, None)
        if metadata is not None:
            return metadata

    if media_type == fom.IMAGE:
        metadata = ImageMetadata.build_for(filepath)
    elif media_type == fom.VIDEO:
        metadata = VideoMetadata.build_for(filepath)
    elif media_type == fom.THREE_D:
        metadata = SceneMetadata.build_for(filepath, _cache=cache)
    else:
        metadata = Metadata.build_for(filepath)

    return metadata
