"""
Dataset exporters.

| Copyright 2017-2021, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
from collections import defaultdict
import inspect
import logging
import os

from bson import json_util

import eta.core.datasets as etad
import eta.core.image as etai
import eta.core.serial as etas
import eta.core.utils as etau

import fiftyone as fo
import fiftyone.core.collections as foc
import fiftyone.core.eta_utils as foe
import fiftyone.core.labels as fol
import fiftyone.core.metadata as fom
import fiftyone.core.media as fomm
import fiftyone.core.odm as foo
import fiftyone.core.utils as fou
import fiftyone.utils.patches as foup
import fiftyone.types as fot

from .parsers import (
    FiftyOneLabeledImageSampleParser,
    FiftyOneUnlabeledImageSampleParser,
    FiftyOneLabeledVideoSampleParser,
    FiftyOneUnlabeledVideoSampleParser,
    ImageSampleParser,
    ImageClassificationSampleParser,
)


logger = logging.getLogger(__name__)


def export_samples(
    samples,
    export_dir=None,
    dataset_type=None,
    dataset_exporter=None,
    label_field_or_dict=None,
    frame_labels_field_or_dict=None,
    num_samples=None,
    export_media=True,
    **kwargs,
):
    """Exports the given samples to disk as a dataset in the specified format.

    Provide either ``export_dir`` and ``dataset_type`` or ``dataset_exporter``
    to perform the export.

    This method will automatically coerce the data to match the requested
    export in the following cases:

    -   When exporting in either an unlabeled image or image classification
        format, if a spatial label field is provided
        (:class:`fiftyone.core.labels.Detection`,
        :class:`fiftyone.core.labels.Detections`,
        :class:`fiftyone.core.labels.Polyline`, or
        :class:`fiftyone.core.labels.Polylines`), then the **image patches** of
        the provided samples will be exported

    -   When exporting in labeled image dataset formats that expect list-type
        labels (:class:`fiftyone.core.labels.Classifications`,
        :class:`fiftyone.core.labels.Detections`,
        :class:`fiftyone.core.labels.Keypoints`, or
        :class:`fiftyone.core.labels.Polylines`), if a label field contains
        labels in non-list format
        (e.g., :class:`fiftyone.core.labels.Classification`), the labels will
        be automatically upgraded to single-label lists

    -   When exporting in labeled image dataset formats that expect
        :class:`fiftyone.core.labels.Detections` labels, if a
        :class:`fiftyone.core.labels.Classification` field is provided, the
        labels will be automatically upgraded to detections that span the
        entire images

    Args:
        samples: a :class:`fiftyone.core.collections.SampleCollection`
        export_dir (None): the directory to which to export the samples in
            format ``dataset_type``
        dataset_type (None): the :class:`fiftyone.types.dataset_types.Dataset`
            type to write
        dataset_exporter (None): a
            :class:`fiftyone.utils.data.exporters.DatasetExporter` to use to
            write the dataset
        label_field_or_dict (None): the name of the label field to export, or
            a dictionary mapping field names to output keys describing the
            label fields to export. Only applicable if ``dataset_exporter`` is
            a :class:`LabeledImageDatasetExporter` or
            :class:`LabeledVideoDatasetExporter`, or if you are exporting image
            patches
        frame_labels_field_or_dict (None): the name of the frame label field to
            export, or a dictionary mapping field names to output keys
            describing the frame label fields to export. Only applicable if
            ``dataset_exporter`` is a :class:`LabeledVideoDatasetExporter`
        num_samples (None): the number of samples in ``samples``. If omitted,
            this is computed (if possible) via ``len(samples)``
        export_media (True): whether to export media files or to export only
            labels and metadata. This argument only applies to certain dataset
            types
        **kwargs: optional keyword arguments to pass to the dataset exporter's
            constructor via ``DatasetExporter(export_dir=export_dir, **kwargs)``.
            If you are exporting image patches, this can also contain keyword
            arguments for :class:`fiftyone.utils.patches.ImagePatchesExtractor`
    """
    found_patches, patches_kwargs, kwargs = _check_for_patches_export(
        samples, dataset_exporter, label_field_or_dict, kwargs
    )

    sample_collection = samples

    if dataset_exporter is None:
        dataset_exporter, kwargs = build_dataset_exporter(
            dataset_type,
            export_dir=export_dir,
            export_media=export_media,
            **kwargs,
        )

    for key, value in kwargs.items():
        if value is not None:
            logger.warning(
                "Ignoring unsupported parameter %s=%s for export type " "%s",
                key,
                value,
                type(dataset_exporter),
            )

    if isinstance(dataset_exporter, BatchDatasetExporter):
        _write_batch_dataset(dataset_exporter, samples)
        return

    if isinstance(dataset_exporter, GenericSampleDatasetExporter):
        sample_parser = None
    elif isinstance(dataset_exporter, UnlabeledImageDatasetExporter):
        if found_patches:
            # Export unlabeled image patches
            samples = foup.ImagePatchesExtractor(
                samples,
                label_field_or_dict,
                include_labels=False,
                **patches_kwargs,
            )
            sample_parser = ImageSampleParser()
            num_samples = len(samples)
        else:
            sample_parser = FiftyOneUnlabeledImageSampleParser(
                compute_metadata=True
            )

    elif isinstance(dataset_exporter, UnlabeledVideoDatasetExporter):
        sample_parser = FiftyOneUnlabeledVideoSampleParser(
            compute_metadata=True
        )

    elif isinstance(dataset_exporter, LabeledImageDatasetExporter):
        if found_patches:
            # Export labeled image patches
            samples = foup.ImagePatchesExtractor(
                samples,
                label_field_or_dict,
                include_labels=True,
                **patches_kwargs,
            )
            sample_parser = ImageClassificationSampleParser()
            num_samples = len(samples)
        else:
            label_fcn_or_dict = _make_label_coersion_functions(
                label_field_or_dict, sample_collection, dataset_exporter
            )
            sample_parser = FiftyOneLabeledImageSampleParser(
                label_field_or_dict,
                label_fcn_or_dict=label_fcn_or_dict,
                compute_metadata=True,
            )

    elif isinstance(dataset_exporter, LabeledVideoDatasetExporter):
        label_fcn_or_dict = _make_label_coersion_functions(
            label_field_or_dict, sample_collection, dataset_exporter
        )
        frame_labels_fcn_or_dict = _make_label_coersion_functions(
            frame_labels_field_or_dict,
            sample_collection,
            dataset_exporter,
            frames=True,
        )
        sample_parser = FiftyOneLabeledVideoSampleParser(
            label_field_or_dict=label_field_or_dict,
            frame_labels_field_or_dict=frame_labels_field_or_dict,
            label_fcn_or_dict=label_fcn_or_dict,
            frame_labels_fcn_or_dict=frame_labels_fcn_or_dict,
            compute_metadata=True,
        )

    else:
        raise ValueError(
            "Unsupported DatasetExporter %s" % type(dataset_exporter)
        )

    write_dataset(
        samples,
        sample_parser,
        dataset_exporter=dataset_exporter,
        num_samples=num_samples,
        sample_collection=sample_collection,
    )


def write_dataset(
    samples,
    sample_parser,
    dataset_dir=None,
    dataset_type=None,
    dataset_exporter=None,
    num_samples=None,
    export_media=True,
    sample_collection=None,
    **kwargs,
):
    """Writes the samples to disk as a dataset in the specified format.

    Provide either ``dataset_dir`` and ``dataset_type`` or ``dataset_exporter``
    to perform the write.

    Args:
        samples: an iterable of samples that can be parsed by ``sample_parser``
        sample_parser: a :class:`fiftyone.utils.data.parsers.SampleParser` to
            use to parse the samples
        dataset_dir (None): the directory to which to write the dataset in
            format ``dataset_type``
        dataset_type (None): the :class:`fiftyone.types.dataset_types.Dataset`
            type to write
        dataset_exporter (None): a
            :class:`fiftyone.utils.data.exporters.DatasetExporter` to use to
            write the dataset
        num_samples (None): the number of samples in ``samples``. If omitted,
            this is computed (if possible) via ``len(samples)``
        export_media (True): whether to export media files or to export only
            labels and metadata. This argument only applies to certain dataset
            types
        sample_collection (None): the
            :class:`fiftyone.core.collections.SampleCollection` from which
            ``samples`` were extracted. If ``samples`` is itself a
            :class:`fiftyone.core.collections.SampleCollection`, this parameter
            defaults to ``samples``. This parameter is optional and is only
            passed to :meth:`DatasetExporter.log_collection`
        **kwargs: optional keyword arguments to pass to the dataset exporter's
            constructor via
            ``DatasetExporter(export_dir=dataset_dir, **kwargs)``
    """
    if dataset_exporter is None:
        dataset_exporter, kwargs = build_dataset_exporter(
            dataset_type,
            export_dir=dataset_dir,
            export_media=export_media,
            **kwargs,
        )

    for key, value in kwargs.items():
        if value is not None:
            logger.warning(
                "Ignoring unsupported parameter %s=%s for export type " "%s",
                key,
                value,
                type(dataset_exporter),
            )

    if num_samples is None:
        try:
            num_samples = len(samples)
        except:
            pass

    if sample_collection is None and isinstance(samples, foc.SampleCollection):
        sample_collection = samples

    if isinstance(dataset_exporter, GenericSampleDatasetExporter):
        _write_generic_sample_dataset(
            dataset_exporter,
            samples,
            num_samples=num_samples,
            sample_collection=sample_collection,
        )
    elif isinstance(
        dataset_exporter,
        (UnlabeledImageDatasetExporter, LabeledImageDatasetExporter),
    ):
        _write_image_dataset(
            dataset_exporter,
            samples,
            sample_parser,
            num_samples=num_samples,
            sample_collection=sample_collection,
        )
    elif isinstance(
        dataset_exporter,
        (UnlabeledVideoDatasetExporter, LabeledVideoDatasetExporter),
    ):
        _write_video_dataset(
            dataset_exporter,
            samples,
            sample_parser,
            num_samples=num_samples,
            sample_collection=sample_collection,
        )
    else:
        raise ValueError(
            "Unsupported DatasetExporter %s" % type(dataset_exporter)
        )


def build_dataset_exporter(dataset_type, export_dir=None, **kwargs):
    """Builds the :class:`DatasetExporter` instance for the given parameters.

    Args:
        dataset_type: the :class:`fiftyone.types.dataset_types.Dataset` type
        export_dir (None): the export directory
        **kwargs: optional keyword arguments to pass to the dataset exporter's
            constructor via
            ``DatasetExporter(export_dir=export_dir, **kwargs)``

    Returns:
        a tuple of:

        -   the :class:`DatasetExporter` instance
        -   a dict of extra keyword arguments that were unused
    """
    if dataset_type is None:
        raise ValueError("You must provide a `dataset_type`")

    if inspect.isclass(dataset_type):
        dataset_type = dataset_type()

    if not isinstance(
        dataset_type,
        (
            fot.UnlabeledImageDataset,
            fot.LabeledImageDataset,
            fot.UnlabeledVideoDataset,
            fot.LabeledVideoDataset,
        ),
    ):
        raise ValueError("Unsupported `dataset_type` %s" % type(dataset_type))

    dataset_exporter_cls = dataset_type.get_dataset_exporter_cls()

    kwargs, other_kwargs = fou.extract_kwargs_for_class(
        dataset_exporter_cls, kwargs
    )

    try:
        dataset_exporter = dataset_exporter_cls(
            export_dir=export_dir, **kwargs
        )
    except Exception as e:
        raise ValueError(
            "Failed to construct exporter using syntax "
            "%s(export_dir=export_dir, **kwargs); you may need to supply "
            "mandatory arguments to the constructor via `kwargs`. Please "
            "consult the documentation of %s to learn more"
            % (dataset_exporter_cls.__name__, dataset_exporter_cls)
        ) from e

    return dataset_exporter, other_kwargs


def _check_for_patches_export(
    samples, dataset_exporter, label_field_or_dict, kwargs
):
    if isinstance(label_field_or_dict, dict):
        if len(label_field_or_dict) == 1:
            label_field = next(iter(label_field_or_dict.keys()))
        else:
            label_field = None
    else:
        label_field = label_field_or_dict

    if label_field is None:
        return False, {}, kwargs

    found_patches = False

    if isinstance(dataset_exporter, UnlabeledImageDatasetExporter):
        try:
            label_type = samples._get_label_field_type(label_field)
            found_patches = issubclass(label_type, fol._PATCHES_FIELDS)
        except:
            pass

        if found_patches:
            logger.info(
                "Detected an unlabeled image exporter and a label field '%s' "
                "of type %s. Exporting image patches...",
                label_field,
                label_type,
            )

    elif (
        isinstance(dataset_exporter, LabeledImageDatasetExporter)
        and dataset_exporter.label_cls is fol.Classification
    ):
        try:
            label_type = samples._get_label_field_type(label_field)
            found_patches = issubclass(label_type, fol._PATCHES_FIELDS)
        except:
            pass

        if found_patches:
            logger.info(
                "Detected an image classification exporter and a label field "
                "'%s' of type %s. Exporting image patches...",
                label_field,
                label_type,
            )

    if found_patches:
        patches_kwargs, kwargs = fou.extract_kwargs_for_class(
            foup.ImagePatchesExtractor, kwargs
        )
    else:
        patches_kwargs = {}

    return found_patches, patches_kwargs, kwargs


def _make_label_coersion_functions(
    label_field_or_dict, sample_collection, dataset_exporter, frames=False
):
    if frames:
        label_cls = dataset_exporter.frame_labels_cls
    else:
        label_cls = dataset_exporter.label_cls

    if label_cls is None:
        return None

    return_dict = isinstance(label_field_or_dict, dict)

    if return_dict:
        label_fields = list(label_field_or_dict.keys())
    else:
        label_fields = [label_field_or_dict]

    if isinstance(label_cls, dict):
        export_types = list(label_cls.values())
    else:
        export_types = [label_cls]

    coerce_fcn_dict = {}
    for label_field in label_fields:
        if frames:
            field = sample_collection._FRAMES_PREFIX + label_field
        else:
            field = label_field

        try:
            label_type = sample_collection._get_label_field_type(field)
        except:
            continue

        if any(issubclass(label_type, t) for t in export_types):
            continue

        #
        # Single label -> list coersion
        #

        for export_type in export_types:
            single_label_type = fol._LABEL_LIST_TO_SINGLE_MAP.get(
                export_type, None
            )
            if issubclass(label_type, single_label_type):
                logger.info(
                    "Dataset exporter expects labels in %s format, but found "
                    "%s. Wrapping field '%s' as single-label lists...",
                    export_type,
                    label_type,
                    label_field,
                )

                coerce_fcn_dict[label_field] = _make_single_label_to_list_fcn(
                    export_type
                )
                break

        if label_field in coerce_fcn_dict:
            continue

        #
        # `Classification` -> `Detections` coersion
        #

        if (
            issubclass(label_type, fol.Classification)
            and fol.Detections in export_types
        ):
            logger.info(
                "Dataset exporter expects labels in %s format, but found %s. "
                "Converting field '%s' to detections whose bounding boxes "
                "span the entire image...",
                fol.Detections,
                label_type,
                label_field,
            )

            coerce_fcn_dict[label_field] = _classification_to_detections

    if not coerce_fcn_dict:
        return None

    if not return_dict:
        return next(iter(coerce_fcn_dict.values()))

    return coerce_fcn_dict


def _make_single_label_to_list_fcn(label_cls):
    def single_label_to_list(label):
        if label is None:
            return label

        return label_cls(**{label_cls._LABEL_LIST_FIELD: [label]})

    return single_label_to_list


def _classification_to_detections(label):
    if label is None:
        return label

    return fol.Detections(
        detections=[
            fol.Detection(
                label=label.label,
                bounding_box=[0, 0, 1, 1],
                confidence=label.confidence,
            )
        ]
    )


def _write_batch_dataset(dataset_exporter, samples):
    if not isinstance(samples, foc.SampleCollection):
        raise ValueError(
            "%s can only export %s instances"
            % (type(dataset_exporter), foc.SampleCollection)
        )

    with dataset_exporter:
        dataset_exporter.export_samples(samples)


def _write_generic_sample_dataset(
    dataset_exporter, samples, num_samples=None, sample_collection=None,
):
    with fou.ProgressBar(total=num_samples) as pb:
        with dataset_exporter:
            if sample_collection is not None:
                dataset_exporter.log_collection(sample_collection)

            for sample in pb(samples):
                dataset_exporter.export_sample(sample)


def _write_image_dataset(
    dataset_exporter,
    samples,
    sample_parser,
    num_samples=None,
    sample_collection=None,
):
    labeled_images = isinstance(dataset_exporter, LabeledImageDatasetExporter)

    with fou.ProgressBar(total=num_samples) as pb:
        with dataset_exporter:
            if sample_collection is not None:
                dataset_exporter.log_collection(sample_collection)

            for sample in pb(samples):
                sample_parser.with_sample(sample)

                # Parse image
                if sample_parser.has_image_path:
                    try:
                        image_or_path = sample_parser.get_image_path()
                    except:
                        image_or_path = sample_parser.get_image()
                else:
                    image_or_path = sample_parser.get_image()

                # Parse metadata
                if dataset_exporter.requires_image_metadata:
                    if sample_parser.has_image_metadata:
                        metadata = sample_parser.get_image_metadata()
                    else:
                        metadata = None

                    if metadata is None:
                        metadata = fom.ImageMetadata.build_for(image_or_path)
                else:
                    metadata = None

                if labeled_images:
                    # Parse label
                    label = sample_parser.get_label()

                    # Export sample
                    dataset_exporter.export_sample(
                        image_or_path, label, metadata=metadata
                    )
                else:
                    # Export sample
                    dataset_exporter.export_sample(
                        image_or_path, metadata=metadata
                    )


def _write_video_dataset(
    dataset_exporter,
    samples,
    sample_parser,
    num_samples=None,
    sample_collection=None,
):
    labeled_videos = isinstance(dataset_exporter, LabeledVideoDatasetExporter)

    with fou.ProgressBar(total=num_samples) as pb:
        with dataset_exporter:
            if sample_collection is not None:
                dataset_exporter.log_collection(sample_collection)

            for sample in pb(samples):
                sample_parser.with_sample(sample)

                # Parse video
                video_path = sample_parser.get_video_path()

                # Parse metadata
                if dataset_exporter.requires_video_metadata:
                    if sample_parser.has_video_metadata:
                        metadata = sample_parser.get_video_metadata()
                    else:
                        metadata = None

                    if metadata is None:
                        metadata = fom.VideoMetadata.build_for(video_path)
                else:
                    metadata = None

                if labeled_videos:
                    # Parse labels
                    label = sample_parser.get_label()
                    frames = sample_parser.get_frame_labels()

                    # Export sample
                    dataset_exporter.export_sample(
                        video_path, label, frames, metadata=metadata
                    )
                else:
                    # Export sample
                    dataset_exporter.export_sample(
                        video_path, metadata=metadata
                    )


class DatasetExporter(object):
    """Base interface for exporting datsets.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir (None): the directory to write the export
    """

    def __init__(self, export_dir=None):
        if export_dir is not None:
            export_dir = os.path.abspath(os.path.expanduser(export_dir))

        self.export_dir = export_dir

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, *args):
        self.close(*args)

    def setup(self):
        """Performs any necessary setup before exporting the first sample in
        the dataset.

        This method is called when the exporter's context manager interface is
        entered, :func:`DatasetExporter.__enter__`.
        """
        pass

    def log_collection(self, sample_collection):
        """Logs any relevant information about the
        :class:`fiftyone.core.collections.SampleCollection` whose samples will
        be exported.

        Subclasses can optionally implement this method if their export format
        can record information such as the
        :meth:`fiftyone.core.collections.SampleCollection.info` or
        :meth:`fiftyone.core.collections.SampleCollection.classes` of the
        collection being exported.

        By convention, this method must be optional; i.e., if it is not called
        before the first call to :meth:`export_sample`, then the exporter must
        make do without any information about the
        :class:`fiftyone.core.collections.SampleCollection` (which may not be
        available, for example, if the samples being exported are not stored in
        a collection).

        Args:
            sample_collection: the
                :class:`fiftyone.core.collections.SampleCollection` whose
                samples will be exported
        """
        pass

    def export_sample(self, *args, **kwargs):
        """Exports the given sample to the dataset.

        Args:
            *args: subclass-specific positional arguments
            **kwargs: subclass-specific keyword arguments
        """
        raise NotImplementedError("subclass must implement export_sample()")

    def close(self, *args):
        """Performs any necessary actions after the last sample has been
        exported.

        This method is called when the exporter's context manager interface is
        exited, :func:`DatasetExporter.__exit__`.

        Args:
            *args: the arguments to :func:`DatasetExporter.__exit__`
        """
        pass


class BatchDatasetExporter(DatasetExporter):
    """Base interface for exporters that export entire
    :class:`fiftyone.core.collections.SampleCollection` instances in a single
    batch.

    This interface allows for greater efficiency for export formats that
    handle aggregating over the samples themselves.

    Args:
        export_dir (None): the directory to write the export
    """

    def export_sample(self, *args, **kwargs):
        raise ValueError(
            "Use export_samples() to perform exports with %s instances"
            % self.__class__
        )

    def export_samples(self, sample_collection):
        """Exports the given sample collection.

        Args:
            sample_collection: a
                :class:`fiftyone.core.collections.SampleCollection`
        """
        raise NotImplementedError("subclass must implement export_samples()")


class GenericSampleDatasetExporter(DatasetExporter):
    """Interface for exporting datasets of arbitrary
    :class:`fiftyone.core.sample.Sample` instances.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir: the directory to write the export
    """

    def export_sample(self, sample):
        """Exports the given sample to the dataset.

        Args:
            sample: a :class:`fiftyone.core.sample.Sample`
        """
        raise NotImplementedError("subclass must implement export_sample()")


class UnlabeledImageDatasetExporter(DatasetExporter):
    """Interface for exporting datasets of unlabeled image samples.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir: the directory to write the export
    """

    @property
    def requires_image_metadata(self):
        """Whether this exporter requires
        :class:`fiftyone.core.metadata.ImageMetadata` instances for each sample
        being exported.
        """
        raise NotImplementedError(
            "subclass must implement requires_image_metadata"
        )

    def export_sample(self, image_or_path, metadata=None):
        """Exports the given sample to the dataset.

        Args:
            image_or_path: an image or the path to the image on disk
            metadata (None): a :class:`fiftyone.core.metadata.ImageMetadata`
                instance for the sample. Only required when
                :meth:`requires_image_metadata` is ``True``
        """
        raise NotImplementedError("subclass must implement export_sample()")


class UnlabeledVideoDatasetExporter(DatasetExporter):
    """Interface for exporting datasets of unlabeled video samples.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir: the directory to write the export
    """

    @property
    def requires_video_metadata(self):
        """Whether this exporter requires
        :class:`fiftyone.core.metadata.VideoMetadata` instances for each sample
        being exported.
        """
        raise NotImplementedError(
            "subclass must implement requires_video_metadata"
        )

    def export_sample(self, video_path, metadata=None):
        """Exports the given sample to the dataset.

        Args:
            video_path: the path to a video on disk
            metadata (None): a :class:`fiftyone.core.metadata.VideoMetadata`
                instance for the sample. Only required when
                :meth:`requires_video_metadata` is ``True``
        """
        raise NotImplementedError("subclass must implement export_sample()")


class LabeledImageDatasetExporter(DatasetExporter):
    """Interface for exporting datasets of labeled image samples.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir: the directory to write the export
    """

    @property
    def requires_image_metadata(self):
        """Whether this exporter requires
        :class:`fiftyone.core.metadata.ImageMetadata` instances for each sample
        being exported.
        """
        raise NotImplementedError(
            "subclass must implement requires_image_metadata"
        )

    @property
    def label_cls(self):
        """The :class:`fiftyone.core.labels.Label` class(es) exported by this
        exporter.

        This can be any of the following:

        -   a :class:`fiftyone.core.labels.Label` class. In this case, the
            exporter directly exports labels of this type
        -   a dict mapping keys to :class:`fiftyone.core.labels.Label` classes.
            In this case, the exporter can handle label dictionaries with
            value-types specified by this dictionary. Not all keys need be
            present in the exported label dicts
        -   ``None``. In this case, the exporter makes no guarantees about the
            labels that it can export
        """
        raise NotImplementedError("subclass must implement label_cls")

    def export_sample(self, image_or_path, label, metadata=None):
        """Exports the given sample to the dataset.

        Args:
            image_or_path: an image or the path to the image on disk
            label: an instance of :meth:`label_cls`, or a dictionary mapping
                field names to :class:`fiftyone.core.labels.Label` instances,
                or ``None`` if the sample is unlabeled
            metadata (None): a :class:`fiftyone.core.metadata.ImageMetadata`
                instance for the sample. Only required when
                :meth:`requires_image_metadata` is ``True``
        """
        raise NotImplementedError("subclass must implement export_sample()")


class LabeledVideoDatasetExporter(DatasetExporter):
    """Interface for exporting datasets of labeled video samples.

    See `this page <https://voxel51.com/docs/fiftyone/user_guide/export_datasets.html#writing-a-custom-datasetexporter>`_
    for information about implementing/using dataset exporters.

    Args:
        export_dir: the directory to write the export
        export_media (True): whether to export media files or to export only
            labels and metadata
    """

    @property
    def requires_video_metadata(self):
        """Whether this exporter requires
        :class:`fiftyone.core.metadata.VideoMetadata` instances for each sample
        being exported.
        """
        raise NotImplementedError(
            "subclass must implement requires_video_metadata"
        )

    @property
    def label_cls(self):
        """The :class:`fiftyone.core.labels.Label` class(es) that can be
        exported at the sample-level.

        This can be any of the following:

        -   a :class:`fiftyone.core.labels.Label` class. In this case, the
            exporter directly exports sample-level labels of this type
        -   a dict mapping keys to :class:`fiftyone.core.labels.Label` classes.
            In this case, the exporter can export multiple label fields with
            value-types specified by this dictionary. Not all keys need be
            present in the exported sample-level labels
        -   ``None``. In this case, the exporter makes no guarantees about the
            sample-level labels that it can export
        """
        raise NotImplementedError("subclass must implement label_cls")

    @property
    def frame_labels_cls(self):
        """The :class:`fiftyone.core.labels.Label` class(es) that can be
        exported by this exporter at the frame-level.

        This can be any of the following:

        -   a :class:`fiftyone.core.labels.Label` class. In this case, the
            exporter directly exports frame labels of this type
        -   a dict mapping keys to :class:`fiftyone.core.labels.Label` classes.
            In this case, the exporter can export multiple frame label fields
            with value-types specified by this dictionary. Not all keys need be
            present in the exported frame labels
        -   ``None``. In this case, the exporter makes no guarantees about the
            frame labels that it can export
        """
        raise NotImplementedError("subclass must implement frame_labels_cls")

    def export_sample(self, video_path, label, frames, metadata=None):
        """Exports the given sample to the dataset.

        Args:
            video_path: the path to a video on disk
            label: an instance of :meth:`label_cls`, or a dictionary mapping
                field names to :class:`fiftyone.core.labels.Label` instances,
                or ``None`` if the sample has no sample-level labels
            frames: a dictionary mapping frame numbers to dictionaries that map
                field names to :class:`fiftyone.core.labels.Label` instances,
                or ``None`` if the sample has no frame-level labels
            metadata (None): a :class:`fiftyone.core.metadata.VideoMetadata`
                instance for the sample. Only required when
                :meth:`requires_video_metadata` is ``True``
        """
        raise NotImplementedError("subclass must implement export_sample()")


class ExportsMedia(object):
    """Base class for :class:`DatasetExporter` mixins that implement the export
    of media files.
    """

    def __init__(self):
        self._export_media = None
        self._ignore_exts = None
        self._filename_maker = None
        self._data_map = None
        self._data_path = None

    def _write_media(self, media, outpath):
        raise NotImplementedError("subclass must implement _write_media()")

    def _get_uuid(self, media_path):
        filename = os.path.basename(media_path)
        if self._ignore_exts:
            return os.path.splitext(filename)[0]

        return filename

    def _setup(
        self, export_media, data_path, default_ext="", ignore_exts=False
    ):
        """Performs necessary setup to begin exporting media.

        :class:`DatasetExporter` classes implementing this mixin should invoke
        this method in :meth:`DatasetExporter.setup`.

        Args:
            export_media: controls how to export the raw media. The supported
                values are:

                -   ``True``: copy all media files into the output directory
                -   ``False``: write a JSON mapping file that maps UUIDs in the
                    labels files to the filepaths of the source media
                -   ``"move"``: move all media files into the output directory
                -   ``"symlink"``: create symlinks to the media files in the
                    output directory
            data_path: the location to export the media. Can be any of the
                following:

                -   When ``export_media`` is True, "move", or "symlink", a
                    directory in which to export the media
                -   When ``export_media`` is False, a JSON filepath to write
                    the JSON mapping file
            default_ext (""): the file extension to use when generating default
                output paths
            ignore_exts (False): whether to omit file extensions when checking
                for duplicate filenames
        """
        if export_media in {True, "move", "symlink"}:
            output_dir = data_path
            data_path = None
            data_map = None
        elif export_media == False:
            output_dir = ""
            data_map = {}
        else:
            raise ValueError(
                "Unsupported export_media: %s. Supported values are %s"
                % (export_media, (True, False, "move", "symlink"))
            )

        self._export_media = export_media
        self._ignore_exts = ignore_exts
        self._filename_maker = fou.UniqueFilenameMaker(
            output_dir=output_dir,
            default_ext=default_ext,
            ignore_exts=ignore_exts,
        )
        self._data_path = data_path
        self._data_map = data_map

    def _export_media_or_path(self, media_or_path):
        """Exports the given media via the configured method.

        Args:
            media_or_path: the media or path to the media on disk

        Returns:
            the path to the exported media
        """
        if etau.is_str(media_or_path):
            media_path = media_or_path
            outpath = self._filename_maker.get_output_path(media_path)

            if self._export_media == True:
                etau.copy_file(media_path, outpath)
            if self._export_media == "move":
                etau.move_file(media_path, outpath)
            elif self._export_media == "symlink":
                etau.symlink_file(media_path, outpath)
            else:
                uuid = self._get_uuid(outpath)
                self._data_map[uuid] = media_path
        else:
            media = media_or_path
            outpath = self._filename_maker.get_output_path()

            if self._export_media == True:
                self._write_media(media, outpath)
            else:
                raise ValueError(
                    "Cannot export in-memory media when 'export_media=%s'"
                    % self._export_media
                )

        return outpath

    def _close(self):
        """Performs any necessary actions to complete an export.

        :class:`DatasetExporter` classes implementing this mixin should invoke
        this method in :meth:`DatasetExporter.close`.
        """
        if self._export_media == False:
            etas.write_json(self._data_map, self._data_path)


class ExportsImages(ExportsMedia):
    """Mixin for :class:`DatasetExporter` mixins that export images."""

    def _write_media(self, img, outpath):
        etai.write(img, outpath)


class ExportsVideos(ExportsMedia):
    """Mixin for :class:`DatasetExporter` mixins that export videos."""

    def _write_media(self, media, outpath):
        raise ValueError("Only video paths can be exported")


class LegacyFiftyOneDatasetExporter(GenericSampleDatasetExporter):
    """Legacy exporter that writes an entire FiftyOne dataset to disk in a
    serialized JSON format along with its source media.

    .. warning::

        The :class:`fiftyone.types.dataset_types.FiftyOneDataset` format was
        upgraded in ``fiftyone==0.8`` and this exporter is now deprecated.
        The new exporter is :class:`FiftyOneDatasetExporter`.

    Args:
        export_dir: the directory to write the export
        export_media (True): defines how to export the raw media contained
            in the dataset. Options for this argument include:

            -   ``True``: copy and export all media files
            -   ``False``: avoid exporting media, filepaths are stored in
                exported labels
            -   ``"move"``: move media files instead of copying
            -   ``"symlink"``: create a symbolic link to every media file
                instead of copying

        relative_filepaths (True): whether to store relative (True) or absolute
            (False) filepaths to media files on disk in the output dataset
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """

    def __init__(
        self,
        export_dir,
        export_media=True,
        relative_filepaths=True,
        pretty_print=False,
    ):
        super().__init__(export_dir)
        self.export_media = export_media
        self.relative_filepaths = relative_filepaths
        self.pretty_print = pretty_print
        self._data_dir = None
        self._eval_dir = None
        self._brain_dir = None
        self._frame_labels_dir = None
        self._metadata_path = None
        self._samples_path = None
        self._metadata = None
        self._samples = None
        self._filename_maker = None
        self._data_map = {}
        self._is_video_dataset = False

    def setup(self):
        self._data_dir = os.path.join(self.export_dir, "data")
        self._eval_dir = os.path.join(self.export_dir, "evaluations")
        self._brain_dir = os.path.join(self.export_dir, "brain")
        self._frame_labels_dir = os.path.join(self.export_dir, "frames")
        self._data_json_path = os.path.join(self.export_dir, "data.json")
        self._metadata_path = os.path.join(self.export_dir, "metadata.json")
        self._samples_path = os.path.join(self.export_dir, "samples.json")
        self._metadata = {}
        self._samples = []

        if not self.export_media:
            output_dir = ""
        else:
            output_dir = self._data_dir

        self._filename_maker = fou.UniqueFilenameMaker(output_dir=output_dir)

    def log_collection(self, sample_collection):
        self._is_video_dataset = sample_collection.media_type == fomm.VIDEO

        self._metadata["name"] = sample_collection.name
        self._metadata["media_type"] = sample_collection.media_type

        schema = sample_collection._serialize_field_schema()
        self._metadata["sample_fields"] = schema

        if self._is_video_dataset:
            schema = sample_collection._serialize_frame_field_schema()
            self._metadata["frame_fields"] = schema

        info = dict(sample_collection.info)

        # Package classes and mask targets into `info`, since the import API
        # only supports checking for `info`

        if sample_collection.classes:
            info["classes"] = sample_collection.classes

        if sample_collection.default_classes:
            info["default_classes"] = sample_collection.default_classes

        if sample_collection.mask_targets:
            info["mask_targets"] = sample_collection._serialize_mask_targets()

        if sample_collection.default_mask_targets:
            info[
                "default_mask_targets"
            ] = sample_collection._serialize_default_mask_targets()

        self._metadata["info"] = info

        # Exporting runs only makes sense if the entire dataset is being
        # exported, otherwise the view for the run cannot be reconstructed
        # based on the information encoded in the run's document

        dataset = sample_collection._root_dataset
        if sample_collection != dataset:
            return

        if dataset.has_evaluations:
            d = dataset._doc.field_to_mongo("evaluations")
            d = {k: json_util.dumps(v) for k, v in d.items()}
            self._metadata["evaluations"] = d
            _export_evaluation_results(dataset, self._eval_dir)

        if dataset.has_brain_runs:
            d = dataset._doc.field_to_mongo("brain_methods")
            d = {k: json_util.dumps(v) for k, v in d.items()}
            self._metadata["brain_methods"] = d
            _export_brain_results(dataset, self._brain_dir)

    def export_sample(self, sample):
        sd = sample.to_dict()

        out_filepath = self._filename_maker.get_output_path(sample.filepath)
        if self.export_media == True:
            etau.copy_file(sample.filepath, out_filepath)
        elif self.export_media == "move":
            etau.move_file(sample.filepath, out_filepath)
        elif self.export_media == "symlink":
            etau.symlink_file(sample.filepath, out_filepath)
        elif self.export_media != False:
            self._data_map[out_filepath] = sample.filepath
        else:
            raise ValueError(
                "Unsupported export_media: %s. Supported values are %s"
                % (self.export_media, (True, False, "move", "symlink"))
            )

        sd["filepath"] = out_filepath

        if self.relative_filepaths:
            sd["filepath"] = os.path.relpath(out_filepath, self.export_dir)

        if self._is_video_dataset:
            # Serialize frame labels separately
            uuid = os.path.splitext(os.path.basename(out_filepath))[0]
            outpath = self._export_frame_labels(sample, uuid)
            sd["frames"] = os.path.relpath(outpath, self.export_dir)

        self._samples.append(sd)

    def close(self, *args):
        samples = {"samples": self._samples}
        etas.write_json(
            self._metadata, self._metadata_path, pretty_print=self.pretty_print
        )
        etas.write_json(
            samples, self._samples_path, pretty_print=self.pretty_print
        )

        if not self.export_media:
            etas.write_json(self._data_map, self._data_json_path)

    def _export_frame_labels(self, sample, uuid):
        frames_dict = {"frames": sample.frames._to_frames_dict()}
        outpath = os.path.join(self._frame_labels_dir, uuid + ".json")
        etas.write_json(frames_dict, outpath, pretty_print=self.pretty_print)

        return outpath


class FiftyOneDatasetExporter(BatchDatasetExporter):
    """Exporter that writes an entire FiftyOne dataset to disk in a serialized
    JSON format along with its source media.

    See :class:`fiftyone.types.dataset_types.FiftyOneDataset` for format
    details.

    Args:
        export_dir: the directory to write the export
        export_media (True): defines how to export the raw media contained
            in the dataset. Options for this argument include:

            -   ``True``: copy and export all media files
            -   ``False``: avoid exporting media, filepaths are stored in
                exported labels
            -   ``"move"``: move media files instead of copying
            -   ``"symlink"``: create a symbolic link to every media file
                instead of copying

        rel_dir (None): a relative directory to remove from the ``filepath`` of
            each sample, if possible. The path is converted to an absolute path
            (if necessary) via ``os.path.abspath(os.path.expanduser(rel_dir))``.
            The typical use case for this argument is that your source data
            lives in a single directory and you wish to serialize relative,
            rather than absolute, paths to the data within that directory.
            Only applicable when ``export_media`` is False
    """

    def __init__(self, export_dir, export_media=True, rel_dir=None):
        super().__init__(export_dir)
        self.export_media = export_media
        self.rel_dir = rel_dir
        self._data_dir = None
        self._eval_dir = None
        self._brain_dir = None
        self._metadata_path = None
        self._samples_path = None
        self._frames_path = None
        self._filename_maker = None

    def setup(self):
        self._data_dir = os.path.join(self.export_dir, "data")
        self._eval_dir = os.path.join(self.export_dir, "evaluations")
        self._brain_dir = os.path.join(self.export_dir, "brain")
        self._metadata_path = os.path.join(self.export_dir, "metadata.json")
        self._samples_path = os.path.join(self.export_dir, "samples.json")
        self._frames_path = os.path.join(self.export_dir, "frames.json")

        if self.export_media != False:
            self._filename_maker = fou.UniqueFilenameMaker(
                output_dir=self._data_dir
            )

    def export_samples(self, sample_collection):
        etau.ensure_dir(self.export_dir)

        inpaths = sample_collection.values("filepath")

        if self.export_media != False:
            if self.rel_dir is not None:
                logger.warning(
                    "Ignoring `rel_dir` since `export_media` is True"
                )

            outpaths = [
                self._filename_maker.get_output_path(p) for p in inpaths
            ]

            # Replace filepath prefixes with `data/` for samples export
            _outpaths = ["data/" + os.path.basename(p) for p in outpaths]
        elif self.rel_dir is not None:
            # Remove `rel_dir` prefix from filepaths
            rel_dir = (
                os.path.abspath(os.path.expanduser(self.rel_dir)) + os.path.sep
            )
            len_rel_dir = len(rel_dir)

            _outpaths = [
                p[len_rel_dir:] if p.startswith(rel_dir) else p
                for p in inpaths
            ]
        else:
            # Export raw filepaths
            _outpaths = inpaths

        logger.info("Exporting samples...")
        num_samples = sample_collection.count()
        samples = list(sample_collection._aggregate(detach_frames=True))

        for sample, filepath in zip(samples, _outpaths):
            sample["filepath"] = filepath

        foo.export_collection(
            samples, self._samples_path, key="samples", num_docs=num_samples
        )

        if sample_collection.media_type == fomm.VIDEO:
            logger.info("Exporting frames...")
            num_frames = sample_collection.count("frames")
            frames = sample_collection._aggregate(frames_only=True)
            foo.export_collection(
                frames, self._frames_path, key="frames", num_docs=num_frames
            )

        conn = foo.get_db_conn()
        dataset = sample_collection._dataset
        dataset_dict = conn.datasets.find_one({"name": dataset.name})

        # Exporting runs only makes sense if the entire dataset is being
        # exported, otherwise the view for the run cannot be reconstructed
        # based on the information encoded in the run's document

        export_runs = sample_collection == sample_collection._root_dataset

        if not export_runs:
            dataset_dict["evaluations"] = {}
            dataset_dict["brain_methods"] = {}

        foo.export_document(dataset_dict, self._metadata_path)

        if export_runs and sample_collection.has_evaluations:
            _export_evaluation_results(sample_collection, self._eval_dir)

        if export_runs and sample_collection.has_brain_runs:
            _export_brain_results(sample_collection, self._brain_dir)

        if self.export_media == True:
            mode = "copy"
        elif self.export_media == "move":
            mode = "move"
        elif self.export_media == "symlink":
            mode = "symlink"
        else:
            mode = None

        if mode is not None:
            logger.info("Exporting media...")
            fomm.export_media(inpaths, outpaths, mode=mode)


def _export_evaluation_results(sample_collection, eval_dir):
    for eval_key in sample_collection.list_evaluations():
        results_path = os.path.join(eval_dir, eval_key + ".json")
        results = sample_collection.load_evaluation_results(eval_key)
        if results is not None:
            etas.write_json(results, results_path)


def _export_brain_results(sample_collection, brain_dir):
    for brain_key in sample_collection.list_brain_runs():
        results_path = os.path.join(brain_dir, brain_key + ".json")
        results = sample_collection.load_brain_results(brain_key)
        if results is not None:
            etas.write_json(results, results_path)


class ImageDirectoryExporter(UnlabeledImageDatasetExporter, ExportsImages):
    """Exporter that writes a directory of images to disk.

    See :class:`fiftyone.types.dataset_types.ImageDirectory` for format
    details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
    """

    def __init__(
        self,
        export_dir=None,
        export_media=None,
        data_path=None,
        image_format=None,
    ):
        if data_path is None:
            if export_dir is None:
                raise ValueError(
                    "Either `export_dir` or `data_path` must be provided"
                )

            if export_media == False:
                raise ValueError(
                    "You must provide `data_path` when `export_media` is False"
                )

            data_path = export_dir

        if export_media is None:
            export_media = not data_path.endswith(".json")

        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir=export_dir)
        ExportsImages.__init__(self)

        self.export_media = export_media
        self.data_path = data_path
        self.image_format = image_format

    @property
    def requires_image_metadata(self):
        return False

    def setup(self):
        if os.path.isabs(self.data_path) or self.export_dir is None:
            data_path = self.data_path
        else:
            data_path = os.path.join(self.export_dir, self.data_path)

        self._setup(
            self.export_media,
            data_path,
            default_ext=self.image_format,
            ignore_exts=False,
        )

    def export_sample(self, image_or_path, metadata=None):
        self._export_media_or_path(image_or_path)

    def close(self):
        self._close()


class VideoDirectoryExporter(UnlabeledVideoDatasetExporter, ExportsVideos):
    """Exporter that writes a directory of videos to disk.

    See :class:`fiftyone.types.dataset_types.VideoDirectory` for format
    details.

    If the path to a video is provided, the video is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
    """

    def __init__(self, export_dir=None, export_media=None, data_path=None):
        if data_path is None:
            if export_dir is None:
                raise ValueError(
                    "Either `export_dir` or `data_path` must be provided"
                )

            if export_media == False:
                raise ValueError(
                    "You must provide `data_path` when `export_media` is False"
                )

            data_path = export_dir

        if export_media is None:
            export_media = not data_path.endswith(".json")

        super().__init__(export_dir)
        ExportsVideos.__init__(self)

        self.export_media = export_media
        self.data_path = data_path

    @property
    def requires_video_metadata(self):
        return False

    def setup(self):
        if os.path.isabs(self.data_path) or self.export_dir is None:
            data_path = self.data_path
        else:
            data_path = os.path.join(self.export_dir, self.data_path)

        self._setup(self.export_media, data_path, ignore_exts=False)

    def export_sample(self, video_path, metadata=None):
        self._export_media_or_path(video_path)

    def close(self):
        self._close()


class FiftyOneImageClassificationDatasetExporter(
    LabeledImageDatasetExporter, ExportsImages
):
    """Exporter that writes an image classification dataset to disk in
    FiftyOne's default format.

    See :class:`fiftyone.types.dataset_types.FiftyOneImageClassificationDataset`
    for format details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        classes (None): the list of possible class labels. If not provided,
            this list will be extracted when :meth:`log_collection` is called,
            if possible
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """

    def __init__(
        self, export_dir, classes=None, image_format=None, pretty_print=False,
    ):
        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir)
        ExportsImages.__init__(self)

        self.classes = classes
        self.image_format = image_format
        self.pretty_print = pretty_print
        self._data_dir = None
        self._labels_path = None
        self._labels_dict = None
        self._labels_map_rev = None

    @property
    def requires_image_metadata(self):
        return False

    @property
    def label_cls(self):
        return fol.Classification

    def setup(self):
        self._data_dir = os.path.join(self.export_dir, "data")
        self._labels_path = os.path.join(self.export_dir, "labels.json")
        self._labels_dict = {}

        # @todo implement `export_media`
        self._setup(
            True,
            self._data_dir,
            default_ext=self.image_format,
            ignore_exts=True,
        )

        self._parse_classes()

    def log_collection(self, sample_collection):
        if self.classes is None:
            if sample_collection.default_classes:
                self.classes = sample_collection.default_classes
                self._parse_classes()
            elif sample_collection.classes:
                self.classes = next(iter(sample_collection.classes.values()))
                self._parse_classes()
            elif "classes" in sample_collection.info:
                self.classes = sample_collection.info["classes"]
                self._parse_classes()

    def export_sample(self, image_or_path, classification, metadata=None):
        out_image_path = self._export_media_or_path(image_or_path)

        uuid = os.path.splitext(os.path.basename(out_image_path))[0]
        self._labels_dict[uuid] = _parse_classification(
            classification, labels_map_rev=self._labels_map_rev
        )

    def close(self, *args):
        labels = {
            "classes": self.classes,
            "labels": self._labels_dict,
        }
        etas.write_json(
            labels, self._labels_path, pretty_print=self.pretty_print
        )
        self._close()

    def _parse_classes(self):
        if self.classes is not None:
            self._labels_map_rev = _to_labels_map_rev(self.classes)


class ImageClassificationDirectoryTreeExporter(LabeledImageDatasetExporter):
    """Exporter that writes an image classification directory tree to disk.

    See :class:`fiftyone.types.dataset_types.ImageClassificationDirectoryTree`
    for format details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
    """

    def __init__(self, export_dir, image_format=None):
        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir)
        self.image_format = image_format
        self._class_counts = None
        self._filename_counts = None
        self._default_filename_patt = (
            fo.config.default_sequence_idx + image_format
        )

    @property
    def requires_image_metadata(self):
        return False

    @property
    def label_cls(self):
        return fol.Classification

    def setup(self):
        self._class_counts = defaultdict(int)
        self._filename_counts = defaultdict(int)
        etau.ensure_dir(self.export_dir)

    def export_sample(self, image_or_path, classification, metadata=None):
        is_image_path = etau.is_str(image_or_path)

        _label = _parse_classification(classification)
        if _label is None:
            _label = "_unlabeled"

        self._class_counts[_label] += 1

        if is_image_path:
            image_path = image_or_path
        else:
            img = image_or_path
            image_path = self._default_filename_patt % (
                self._class_counts[_label]
            )

        filename = os.path.basename(image_path)
        name, ext = os.path.splitext(filename)

        key = (_label, filename)
        self._filename_counts[key] += 1
        count = self._filename_counts[key]
        if count > 1:
            filename = name + ("-%d" % count) + ext

        out_image_path = os.path.join(self.export_dir, _label, filename)

        if is_image_path:
            etau.copy_file(image_path, out_image_path)
        else:
            etai.write(img, out_image_path)


class VideoClassificationDirectoryTreeExporter(LabeledVideoDatasetExporter):
    """Exporter that writes a video classification directory tree to disk.

    See :class:`fiftyone.types.dataset_types.VideoClassificationDirectoryTree`
    for format details.

    The source videos are directly copied to their export destination,
    maintaining the original filename, unless a name conflict would occur, in
    which case an index of the form ``"-%d" % count`` is appended to the base
    filename.

    Args:
        export_dir: the directory to write the export
    """

    def __init__(self, export_dir):
        super().__init__(export_dir)
        self._class_counts = None
        self._filename_counts = None

    @property
    def requires_video_metadata(self):
        return False

    @property
    def label_cls(self):
        return fol.Classification

    @property
    def frame_labels_cls(self):
        return None

    def setup(self):
        self._class_counts = defaultdict(int)
        self._filename_counts = defaultdict(int)
        etau.ensure_dir(self.export_dir)

    def export_sample(self, video_path, classification, _, metadata=None):
        _label = _parse_classification(classification)
        if _label is None:
            _label = "_unlabeled"

        self._class_counts[_label] += 1

        filename = os.path.basename(video_path)
        name, ext = os.path.splitext(filename)

        key = (_label, filename)
        self._filename_counts[key] += 1
        count = self._filename_counts[key]
        if count > 1:
            filename = name + ("-%d" % count) + ext

        out_video_path = os.path.join(self.export_dir, _label, filename)

        etau.copy_file(video_path, out_video_path)


class FiftyOneImageDetectionDatasetExporter(
    LabeledImageDatasetExporter, ExportsImages
):
    """Exporter that writes an image detection dataset to disk in FiftyOne's
    default format.

    See :class:`fiftyone.types.dataset_types.FiftyOneImageDetectionDataset` for
    format details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        classes (None): the list of possible class labels. If not provided,
            this list will be extracted when :meth:`log_collection` is called,
            if possible
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """

    def __init__(
        self, export_dir, classes=None, image_format=None, pretty_print=False,
    ):
        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir)
        ExportsImages.__init__(self)

        self.classes = classes
        self.image_format = image_format
        self.pretty_print = pretty_print

        self._data_dir = None
        self._labels_path = None
        self._labels_dict = None
        self._labels_map_rev = None

    @property
    def requires_image_metadata(self):
        return False

    @property
    def label_cls(self):
        return fol.Detections

    def setup(self):
        self._data_dir = os.path.join(self.export_dir, "data")
        self._labels_path = os.path.join(self.export_dir, "labels.json")
        self._labels_dict = {}

        # @todo implement `export_media`
        self._setup(
            True,
            self._data_dir,
            default_ext=self.image_format,
            ignore_exts=True,
        )

        self._parse_classes()

    def log_collection(self, sample_collection):
        if self.classes is None:
            if sample_collection.default_classes:
                self.classes = sample_collection.default_classes
                self._parse_classes()
            elif sample_collection.classes:
                self.classes = next(iter(sample_collection.classes.values()))
                self._parse_classes()
            elif "classes" in sample_collection.info:
                self.classes = sample_collection.info["classes"]
                self._parse_classes()

    def export_sample(self, image_or_path, detections, metadata=None):
        out_image_path = self._export_media_or_path(image_or_path)

        name = os.path.splitext(os.path.basename(out_image_path))[0]
        self._labels_dict[name] = _parse_detections(
            detections, labels_map_rev=self._labels_map_rev
        )

    def close(self, *args):
        labels = {
            "classes": self.classes,
            "labels": self._labels_dict,
        }
        etas.write_json(
            labels, self._labels_path, pretty_print=self.pretty_print
        )
        self._close()

    def _parse_classes(self):
        if self.classes is not None:
            self._labels_map_rev = _to_labels_map_rev(self.classes)


class ImageSegmentationDirectoryExporter(
    LabeledImageDatasetExporter, ExportsImages
):
    """Exporter that writes an image segmentation dataset to disk.

    See :class:`fiftyone.types.dataset_types.ImageSegmentationDirectory` for
    format details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir (None): the directory to write the export
        data_path (None): an optional parameter that enables explicit control
            over the location of the exported media. Can be any of the
            following:

            -   a folder name like "data" or "data/" specifying a subfolder of
                ``export_dir`` in which to export the media
            -   an absolute directory path in which to export the media. In
                this case, the ``export_dir`` has no effect on the location of
                the data
            -   a JSON filename like "data.json" specifying the filename of the
                JSON mapping file in ``export_dir`` generated when
                ``export_media`` is False
            -   an absolute JSON path specifying the location to write the JSON
                mapping file when ``export_media`` is False. In this case,
                ``export_dir`` has no effect on the location of the data

            When applicable, the default value of this parameter will be chosen
            based on the value of the ``export_media`` parameter
        labels_path (None): an optional parameter that enables explicit control
            over the location of the exported segmentation masks. Can be any of
            the following:

            -   a folder name like "labels" or "labels/" specifying the
                location in ``export_dir`` in which to export the masks
            -   an absolute directory in which to export the masks. In this
                case, the ``export_dir`` has no effect on the location of the
                masks

            When applicable, the default value of this parameter will be chosen
            based on the export format so that the labels will be
            exported into ``export_dir``
        export_media (None): controls how to export the raw media. The
            supported values are:

            -   ``True``: copy all media files into the output directory
            -   ``False``: create a ``data.json`` in the output directory that
                maps UUIDs used in the labels files to the filepaths of the
                source media, rather than exporting the actual media files.
                Only applicable for labeled dataset types
            -   ``"move"``: move all media files into the output directory
            -   ``"symlink"``: create symlinks to the media files in the output
                directory

            When necessary, an appropriate default value of this parameter will
            be chosen based on the value of the ``data_path`` parameter
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
        mask_format (".png"): the image format to use when writing masks to
            disk
    """

    def __init__(
        self,
        export_dir=None,
        data_path=None,
        labels_path=None,
        export_media=None,
        image_format=None,
        mask_format=".png",
    ):
        if data_path is None:
            if export_media == False:
                data_path = "data.json"
            else:
                data_path = "data"

        if labels_path is None:
            labels_path = "labels"

        if export_media is None:
            export_media = not data_path.endswith(".json")

        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir=export_dir)
        ExportsImages.__init__(self)

        self.data_path = data_path
        self.labels_path = labels_path
        self.export_media = export_media
        self.image_format = image_format
        self.mask_format = mask_format

        self._data_path = None
        self._labels_dir = None

    @property
    def requires_image_metadata(self):
        return False

    @property
    def label_cls(self):
        return fol.Segmentation

    def setup(self):
        if os.path.isabs(self.data_path) or self.export_dir is None:
            data_path = self.data_path
        else:
            data_path = os.path.join(self.export_dir, self.data_path)

        if os.path.isabs(self.labels_path) or self.export_dir is None:
            labels_dir = self.labels_path
        else:
            labels_dir = os.path.join(self.export_dir, self.labels_path)

        self._data_path = data_path
        self._labels_dir = labels_dir

        self._setup(
            self.export_media,
            data_path,
            default_ext=self.image_format,
            ignore_exts=True,
        )

    def export_sample(self, image_or_path, segmentation, metadata=None):
        out_image_path = self._export_media_or_path(image_or_path)
        name = os.path.splitext(os.path.basename(out_image_path))[0]

        out_mask_path = os.path.join(self._labels_dir, name + self.mask_format)
        etai.write(segmentation.mask, out_mask_path)

    def close(self):
        self._close()


class FiftyOneImageLabelsDatasetExporter(
    LabeledImageDatasetExporter, ExportsImages
):
    """Exporter that writes a labeled image dataset to disk with labels stored
    in `ETA ImageLabels format <https://github.com/voxel51/eta/blob/develop/docs/image_labels_guide.md>`_.

    See :class:`fiftyone.types.dataset_types.FiftyOneImageLabelsDataset` for
    format details.

    If the path to an image is provided, the image is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        image_format (None): the image format to use when writing in-memory
            images to disk. By default, ``fiftyone.config.default_image_ext``
            is used
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """

    def __init__(self, export_dir, image_format=None, pretty_print=False):
        if image_format is None:
            image_format = fo.config.default_image_ext

        super().__init__(export_dir, export_media=False)
        ExportsImages.__init__(self)

        self.image_format = image_format
        self.pretty_print = pretty_print
        self._labeled_dataset = None
        self._data_dir = None
        self._labels_dir = None
        self._description = None

    @property
    def requires_image_metadata(self):
        return False

    @property
    def label_cls(self):
        return {
            "attributes": fol.Classifications,
            "detections": fol.Detections,
            "polylines": fol.Polylines,
            "keypoints": fol.Keypoints,
        }

    def setup(self):
        self._labeled_dataset = etad.LabeledImageDataset.create_empty_dataset(
            self.export_dir
        )
        self._data_dir = self._labeled_dataset.data_dir
        self._labels_dir = self._labeled_dataset.labels_dir

        # @todo implement `export_media`
        self._setup(
            True,
            self._data_dir,
            default_ext=self.image_format,
            ignore_exts=True,
        )

    def log_collection(self, sample_collection):
        self._description = sample_collection.info.get("description", None)

    def export_sample(self, image_or_path, labels, metadata=None):
        out_image_path = self._export_media_or_path(image_or_path)

        name, ext = os.path.splitext(os.path.basename(out_image_path))
        new_image_filename = name + ext
        new_labels_filename = name + ".json"

        _image_labels = foe.to_image_labels(labels)

        if etau.is_str(image_or_path):
            image_labels_path = os.path.join(
                self._labels_dir, new_labels_filename
            )
            _image_labels.write_json(
                image_labels_path, pretty_print=self.pretty_print
            )

            self._labeled_dataset.add_file(
                image_or_path,
                image_labels_path,
                new_data_filename=new_image_filename,
                new_labels_filename=new_labels_filename,
            )
        else:
            self._labeled_dataset.add_data(
                image_or_path,
                _image_labels,
                new_image_filename,
                new_labels_filename,
            )

    def close(self, *args):
        self._labeled_dataset.set_description(self._description)
        self._labeled_dataset.write_manifest()
        self._close()


class FiftyOneVideoLabelsDatasetExporter(
    LabeledVideoDatasetExporter, ExportsVideos
):
    """Exporter that writes a labeled video dataset with labels stored in
    `ETA VideoLabels format <https://github.com/voxel51/eta/blob/develop/docs/video_labels_guide.md>`_.

    See :class:`fiftyone.types.dataset_types.FiftyOneVideoLabelsDataset` for
    format details.

    If the path to a video is provided, the video is directly copied to its
    destination, maintaining the original filename, unless a name conflict
    would occur, in which case an index of the form ``"-%d" % count`` is
    appended to the base filename.

    Args:
        export_dir: the directory to write the export
        pretty_print (False): whether to render the JSON in human readable
            format with newlines and indentations
    """

    def __init__(self, export_dir, pretty_print=False):
        super().__init__(export_dir)
        ExportsVideos.__init__(self)

        self.pretty_print = pretty_print

        self._labeled_dataset = None
        self._data_dir = None
        self._labels_dir = None
        self._description = None

    @property
    def requires_video_metadata(self):
        return False

    @property
    def label_cls(self):
        return None

    @property
    def frame_labels_cls(self):
        return {
            "attributes": fol.Classifications,
            "detections": fol.Detections,
            "polylines": fol.Polylines,
            "keypoints": fol.Keypoints,
        }

    def setup(self):
        self._labeled_dataset = etad.LabeledVideoDataset.create_empty_dataset(
            self.export_dir
        )
        self._data_dir = self._labeled_dataset.data_dir
        self._labels_dir = self._labeled_dataset.labels_dir

        # @todo implement `export_media`
        self._setup(
            True, self._data_dir, ignore_exts=True,
        )

    def log_collection(self, sample_collection):
        self._description = sample_collection.info.get("description", None)

    def export_sample(self, video_path, _, frames, metadata=None):
        out_video_path = self._export_media_or_path(video_path)

        name, ext = os.path.splitext(os.path.basename(out_video_path))
        new_image_filename = name + ext
        new_labels_filename = name + ".json"

        _video_labels = foe.to_video_labels(frames)

        video_labels_path = os.path.join(self._labels_dir, new_labels_filename)
        _video_labels.write_json(
            video_labels_path, pretty_print=self.pretty_print
        )

        self._labeled_dataset.add_file(
            video_path,
            video_labels_path,
            new_data_filename=new_image_filename,
            new_labels_filename=new_labels_filename,
        )

    def close(self, *args):
        self._labeled_dataset.set_description(self._description)
        self._labeled_dataset.write_manifest()
        self._close()


def _parse_classification(classification, labels_map_rev=None):
    if classification is None:
        return None

    label = classification.label
    if labels_map_rev is not None:
        label = labels_map_rev[label]

    return label


def _parse_detections(detections, labels_map_rev=None):
    if detections is None:
        return None

    _detections = []
    for detection in detections.detections:
        label = detection.label
        if labels_map_rev is not None:
            label = labels_map_rev[label]

        _detection = {
            "label": label,
            "bounding_box": detection.bounding_box,
        }
        if detection.confidence is not None:
            _detection["confidence"] = detection.confidence

        if detection.attributes:
            _detection["attributes"] = {
                name: attr.value for name, attr in detection.attributes.items()
            }

        _detections.append(_detection)

    return _detections


def _to_labels_map_rev(classes):
    return {c: i for i, c in enumerate(classes)}
