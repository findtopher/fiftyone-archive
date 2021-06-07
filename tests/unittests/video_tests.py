"""
FiftyOne video-related unit tests.

| Copyright 2017-2021, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
import unittest

import fiftyone as fo
from fiftyone import ViewField as F

from decorators import drop_datasets


class VideoTests(unittest.TestCase):
    @drop_datasets
    def test_video_sample(self):
        sample = fo.Sample(filepath="video.mp4")
        frames = sample.frames

        self.assertEqual(len(frames), 0)
        self.assertFalse(1 in frames, False)

        frame1 = fo.Frame(frame_number=1)
        frame5 = fo.Frame()
        frame3 = fo.Frame(hello="world")

        # Intentionally out of order to test sorting
        frames[1] = frame1
        frames[5] = frame5
        frames[3] = frame3

        self.assertEqual(len(frames), 3)
        self.assertTrue(1 in frames)
        self.assertFalse(2 in frames)
        self.assertTrue(3 in frames)
        self.assertFalse(4 in frames)
        self.assertTrue(5 in frames)

        self.assertTrue(list(frames.keys()), [1, 3, 5])

        frame_numbers = []
        for frame_number, frame in frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertTrue(frame_numbers, [1, 3, 5])

        del frames[3]

        self.assertFalse(3 in frames)
        self.assertTrue(list(frames.keys()), [1, 5])

        frame_numbers = []
        for frame_number, frame in frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertTrue(frame_numbers, [1, 5])

        dataset = fo.Dataset()
        dataset.add_sample(sample)

        self.assertIsNotNone(sample.id)
        self.assertIsNotNone(frame1.id)
        self.assertIsNone(frame3.id)
        self.assertIsNotNone(frame5.id)

        self.assertTrue(len(sample.frames), 2)

        self.assertTrue(1 in sample.frames)
        self.assertFalse(2 in sample.frames)
        self.assertFalse(3 in sample.frames)
        self.assertFalse(4 in sample.frames)
        self.assertTrue(5 in sample.frames)

        frame_numbers = []
        for frame_number, frame in sample.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertTrue(frame_numbers, [1, 5])

    @drop_datasets
    def test_frames_order(self):
        dataset = fo.Dataset()

        sample1 = fo.Sample(filepath="video1.mp4")
        sample1.frames[1] = fo.Frame(frame_number=1)
        sample1.frames[5] = fo.Frame()
        sample1.frames[3] = fo.Frame(hello="world")

        sample2 = fo.Sample(filepath="video2.mp4")

        dataset.add_samples([sample1, sample2])

        sample2.frames[4]["hello"] = "there"
        sample2.save()

        sample2.frames[2]["hello"] = "world"
        sample2.save()

        values = dataset.values("frames.hello")
        self.assertListEqual(
            values, [[None, "world", None], ["world", "there"]]
        )

        frame_numbers1 = []
        for frame_number, frame in sample1.frames.items():
            frame_numbers1.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers1, [1, 3, 5])

        frame_numbers2 = []
        for frame_number, frame in sample2.frames.items():
            frame_numbers2.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers2, [2, 4])

    @drop_datasets
    def test_modify_video_sample(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")
        dataset.add_sample(sample)

        # Intentionally out of order to test sorting
        sample.frames[1] = fo.Frame(frame_number=1)
        sample.frames[5] = fo.Frame()
        sample.frames[3] = fo.Frame(hello="world")

        self.assertEqual(len(sample.frames), 3)
        self.assertIsNone(sample.frames[1].id)
        self.assertIsNone(sample.frames[3].id)
        self.assertIsNone(sample.frames[5].id)

        sample.save()

        self.assertEqual(len(sample.frames), 3)
        self.assertIsNotNone(sample.frames[1].id)
        self.assertIsNotNone(sample.frames[3].id)
        self.assertIsNotNone(sample.frames[5].id)
        self.assertTrue(dataset.has_frame_field("hello"))

        frame2 = sample.frames[2]

        self.assertIsNone(frame2.id)
        self.assertEqual(len(sample.frames), 4)
        self.assertListEqual(list(sample.frames.keys()), [1, 2, 3, 5])

        sample.save()

        self.assertIsNotNone(frame2.id)
        self.assertEqual(len(sample.frames), 4)
        self.assertListEqual(list(sample.frames.keys()), [1, 2, 3, 5])

        del sample.frames[3]

        self.assertEqual(len(sample.frames), 3)
        self.assertListEqual(list(sample.frames.keys()), [1, 2, 5])

        sample.save()

        self.assertEqual(len(sample.frames), 3)
        self.assertListEqual(list(sample.frames.keys()), [1, 2, 5])

        sample.frames.clear()

        self.assertEqual(len(sample.frames), 0)
        self.assertListEqual(list(sample.frames.keys()), [])

        sample.save()

        self.assertEqual(len(sample.frames), 0)
        self.assertListEqual(list(sample.frames.keys()), [])

        sample.frames[1] = fo.Frame(goodbye="world")

        self.assertTrue(dataset.has_frame_field("goodbye"))

        with self.assertRaises(ValueError):
            sample.frames.add_frame(
                2, fo.Frame(foo="bar"), expand_schema=False
            )

    @drop_datasets
    def test_save_frames(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")
        dataset.add_sample(sample)

        frame = fo.Frame()
        sample.frames[1] = frame

        self.assertIsNone(frame.id)
        self.assertFalse(frame._in_db)
        self.assertEqual(len(sample.frames), 1)
        self.assertEqual(dataset.count("frames"), 0)

        sample.save()

        self.assertIsNotNone(frame.id)
        self.assertTrue(frame._in_db)
        self.assertEqual(len(sample.frames), 1)
        self.assertEqual(dataset.count("frames"), 1)

    @drop_datasets
    def test_delete_video_sample(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")
        frame = fo.Frame(hello="world")
        sample.frames[1] = frame
        dataset.add_sample(sample)

        dataset.delete_samples(sample)

        self.assertIsNone(sample.id)
        self.assertIsNone(frame.id)

        dataset.add_sample(sample)

        view = dataset.limit(1)

        dataset.delete_samples(view.first())

        self.assertIsNone(sample.id)
        self.assertIsNone(frame.id)

    @drop_datasets
    def test_video_sample_view(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")

        frame1 = fo.Frame(frame_number=1)
        frame3 = fo.Frame(hello="world")
        frame5 = fo.Frame()

        sample.frames[1] = frame1
        sample.frames[3] = frame3
        sample.frames[5] = frame5

        dataset.add_sample(sample)

        view = dataset.view()

        sample_view = view.first()

        frame_view1 = sample_view.frames[1]
        frame_view3 = sample_view.frames[3]
        frame_view5 = sample_view.frames[5]

        self.assertEqual(len(sample_view.frames), 3)
        self.assertEqual(frame_view1.id, frame1.id)
        self.assertEqual(frame_view3.id, frame3.id)
        self.assertEqual(frame_view5.id, frame5.id)

        sample_view.frames[2] = fo.Frame(foo="bar")

        self.assertEqual(len(sample_view.frames), 4)
        self.assertListEqual(list(sample_view.frames.keys()), [1, 2, 3, 5])

        self.assertTrue(dataset.has_frame_field("foo"))
        self.assertEqual(len(sample.frames), 3)
        self.assertListEqual(list(sample.frames.keys()), [1, 3, 5])

        sample_view.save()

        self.assertEqual(len(sample.frames), 4)
        self.assertListEqual(list(sample.frames.keys()), [1, 2, 3, 5])

        sample_view.frames[1]["hello"] = "goodbye"
        sample_view.frames[3]["hello"] = "goodbye"
        sample_view.save()

        self.assertEqual(sample_view.frames[1]["hello"], "goodbye")
        self.assertEqual(sample_view.frames[3]["hello"], "goodbye")
        self.assertEqual(sample_view.frames[5]["hello"], None)

        self.assertEqual(frame1.hello, "goodbye")
        self.assertEqual(frame3.hello, "goodbye")
        self.assertEqual(frame5.hello, None)

        frame1.hello = "there"
        frame3.hello = "there"

        sample.save()

        self.assertEqual(sample.frames[1].hello, "there")
        self.assertEqual(sample.frames[3].hello, "there")

        # sample view objects are not singletones
        self.assertEqual(sample_view.frames[1].hello, "goodbye")
        self.assertEqual(sample_view.frames[3].hello, "goodbye")

        # but reloading from the view does work
        self.assertEqual(view.first().frames[1].hello, "there")
        self.assertEqual(view.first().frames[3].hello, "there")

        del sample_view.frames[2]
        del sample_view.frames[3]

        self.assertEqual(len(sample_view.frames), 2)
        self.assertEqual(list(sample_view.frames.keys()), [1, 5])

        frame_numbers = []
        for frame_number, frame in sample_view.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers, [1, 5])

        self.assertEqual(len(sample.frames), 4)
        self.assertEqual(list(sample.frames.keys()), [1, 2, 3, 5])

        sample_view.save()

        self.assertEqual(len(sample.frames), 2)
        self.assertEqual(list(sample.frames.keys()), [1, 5])

    @drop_datasets
    def test_save_frame_view(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")

        frame = fo.Frame()
        sample.frames[1] = frame

        dataset.add_sample(sample)

        view = dataset.limit(1)

        frame_view = view.first().frames.first()

        frame_view["hello"] = "world"
        frame_view.save()

        self.assertEqual(frame_view.hello, "world")
        self.assertEqual(frame.hello, "world")
        self.assertEqual(view.first().frames.first().hello, "world")

    @drop_datasets
    def test_frames_view_order(self):
        dataset = fo.Dataset()

        sample1 = fo.Sample(filepath="video1.mp4")
        sample1.frames[1] = fo.Frame(frame_number=1)
        sample1.frames[5] = fo.Frame()
        sample1.frames[3] = fo.Frame(hello="world")

        sample2 = fo.Sample(filepath="video2.mp4")

        dataset.add_samples([sample1, sample2])

        sample2.frames[4]["hello"] = "there"
        sample2.save()

        sample2.frames[2]["hello"] = "world"
        sample2.save()

        view = dataset.select_fields("frames.hello")

        values = view.values("frames.hello")
        self.assertListEqual(
            values, [[None, "world", None], ["world", "there"]]
        )

        sample_view1 = view.first()
        sample_view2 = view.last()

        frame_numbers1 = []
        for frame_number, frame in sample_view1.frames.items():
            frame_numbers1.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers1, [1, 3, 5])

        frame_numbers2 = []
        for frame_number, frame in sample_view2.frames.items():
            frame_numbers2.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers2, [2, 4])

    @drop_datasets
    def test_video_dataset_view_simple(self):
        sample1 = fo.Sample(filepath="video1.mp4")
        sample1.frames[1] = fo.Frame()

        sample2 = fo.Sample(filepath="video2.mp4")
        sample2.frames[2] = fo.Frame()
        sample2.frames[3] = fo.Frame()

        dataset = fo.Dataset()
        dataset.add_samples([sample1, sample2])

        view = dataset.skip(1)

        sample2_view = view.last()

        self.assertEqual(sample2.id, sample2_view.id)
        self.assertEqual(len(sample2_view.frames), 2)
        self.assertFalse(1 in sample2_view.frames)
        self.assertTrue(2 in sample2_view.frames)
        self.assertTrue(3 in sample2_view.frames)
        self.assertListEqual(list(sample2_view.frames.keys()), [2, 3])

        frame_numbers = []
        for frame_number, frame in sample2_view.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers, [2, 3])

        sample2_view.frames[1] = fo.Frame()
        sample2_view.frames[4] = fo.Frame()
        del sample2_view.frames[2]

        self.assertListEqual(list(sample2_view.frames.keys()), [1, 3, 4])

        frame_numbers = []
        for frame_number, frame in sample2_view.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers, [1, 3, 4])

        sample2_view.save()

        self.assertListEqual(list(sample2.frames.keys()), [1, 3, 4])

        frame_numbers = []
        for frame_number, frame in sample2.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers, [1, 3, 4])

    @drop_datasets
    def test_video_frames_filtered(self):
        sample1 = fo.Sample(filepath="video1.mp4")
        sample1.frames[1] = fo.Frame(
            gt=fo.Detections(
                detections=[
                    fo.Detection(label="cat"),
                    fo.Detection(label="dog"),
                ]
            )
        )
        sample1.frames[2] = fo.Frame(
            gt=fo.Detections(
                detections=[
                    fo.Detection(label="dog"),
                    fo.Detection(label="rabbit"),
                ]
            )
        )

        sample2 = fo.Sample(filepath="video2.mp4")
        sample2.frames[2] = fo.Frame(
            gt=fo.Detections(
                detections=[
                    fo.Detection(label="cat"),
                    fo.Detection(label="dog"),
                ]
            )
        )
        sample2.frames[3] = fo.Frame(
            gt=fo.Detections(
                detections=[
                    fo.Detection(label="dog"),
                    fo.Detection(label="rabbit"),
                ]
            )
        )

        dataset = fo.Dataset()
        dataset.add_samples([sample1, sample2])

        view = dataset.filter_labels("frames.gt", F("label") == "cat")

        sample1_view = view.first()

        self.assertTrue(len(sample1_view.frames), 2)
        self.assertTrue(list(sample1_view.frames.keys()), [1, 2])

        frame_numbers = []
        for frame_number, frame in sample1_view.frames.items():
            frame_numbers.append(frame_number)
            self.assertEqual(frame_number, frame.frame_number)

        self.assertListEqual(frame_numbers, [1, 2])

        self.assertEqual(len(sample1_view.frames[1].gt.detections), 1)
        self.assertEqual(len(sample1_view.frames[2].gt.detections), 0)

    @drop_datasets
    def test_video_frames_merge(self):
        dataset = fo.Dataset()

        sample = fo.Sample(filepath="video.mp4")
        sample.frames[1] = fo.Frame(field1="a", field2="b")

        dataset.add_sample(sample)

        view1 = dataset.select_fields("frames.field1")
        view2 = dataset.select_fields("frames.field2")

        self.assertTrue(dataset.has_frame_field("field1"))
        self.assertTrue(dataset.has_frame_field("field2"))
        self.assertTrue(view1.has_frame_field("field1"))
        self.assertFalse(view1.has_frame_field("field2"))
        self.assertFalse(view2.has_frame_field("field1"))
        self.assertTrue(view2.has_frame_field("field2"))

        frame_view1 = view1.first().frames.first()

        self.assertTrue(frame_view1.has_field("field1"))
        self.assertFalse(frame_view1.has_field("field2"))

        self.assertEqual(frame_view1.field1, "a")
        self.assertEqual(frame_view1["field1"], "a")

        with self.assertRaises(AttributeError):
            _ = frame_view1.field2

        with self.assertRaises(KeyError):
            _ = frame_view1["field2"]

        dataset1 = view1.clone()
        dataset2 = view2.clone()

        self.assertTrue(dataset1.has_frame_field("field1"))
        self.assertFalse(dataset1.has_frame_field("field2"))
        self.assertFalse(dataset2.has_frame_field("field1"))
        self.assertTrue(dataset2.has_frame_field("field2"))

        dataset3 = fo.Dataset()
        dataset3.merge_samples(dataset1)
        dataset3.merge_samples(dataset2)
        frame3 = dataset3.first().frames.first()

        self.assertTrue(dataset3.has_frame_field("field1"))
        self.assertTrue(dataset3.has_frame_field("field2"))
        self.assertEqual(frame3["field1"], "a")
        self.assertEqual(frame3["field2"], "b")

        dataset4 = fo.Dataset()
        dataset4.merge_samples(view1)
        dataset4.merge_samples(view2)
        frame4 = dataset4.first().frames.first()

        self.assertTrue(dataset4.has_frame_field("field1"))
        self.assertTrue(dataset4.has_frame_field("field2"))
        self.assertEqual(frame4["field1"], "a")
        self.assertEqual(frame4["field2"], "b")

    @drop_datasets
    def test_merge_video_samples_and_labels(self):
        sample11 = fo.Sample(filepath="video1.mp4")

        sample12 = fo.Sample(filepath="video2.mp4")
        sample12.frames[1] = fo.Frame()
        sample12.frames[2] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="hello"),
                    fo.Detection(label="world"),
                ]
            ),
            predictions1=fo.Detections(
                detections=[
                    fo.Detection(label="hello", confidence=0.99),
                    fo.Detection(label="world", confidence=0.99),
                ]
            ),
            hello="world",
        )
        sample12.frames[3] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="hello"),
                    fo.Detection(label="world"),
                    fo.Detection(label="common"),
                ]
            ),
            predictions1=fo.Detections(
                detections=[
                    fo.Detection(label="hello", confidence=0.99),
                    fo.Detection(label="world", confidence=0.99),
                ]
            ),
            hello="world",
        )
        sample12.frames[4] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="hi"),
                    fo.Detection(label="there"),
                ]
            ),
            hello="world",
        )
        sample12.frames[5] = fo.Frame(ground_truth=None, hello=None)

        dataset1 = fo.Dataset()
        dataset1.add_samples([sample11, sample12])

        ref = sample12.frames[3].ground_truth.detections[2]
        common = ref.copy()
        common._id = ref._id
        common.label = "COMMON"

        sample22 = fo.Sample(filepath="video2.mp4")

        sample22.frames[2] = fo.Frame()
        sample22.frames[3] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    common,
                    fo.Detection(label="foo"),
                    fo.Detection(label="bar"),
                ]
            ),
            predictions2=fo.Detections(
                detections=[
                    fo.Detection(label="foo", confidence=0.99),
                    fo.Detection(label="bar", confidence=0.99),
                ]
            ),
            hello="bar",
        )
        sample22.frames[4] = fo.Frame(ground_truth=None, hello=None)
        sample22.frames[5] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="foo"),
                    fo.Detection(label="bar"),
                ]
            ),
            predictions2=fo.Detections(
                detections=[
                    fo.Detection(label="foo", confidence=0.99),
                    fo.Detection(label="bar", confidence=0.99),
                ]
            ),
            hello="bar",
        )
        sample23 = fo.Sample(filepath="video3.mp4")

        dataset2 = fo.Dataset()
        dataset2.add_samples([sample22, sample23])

        filepath_fcn = lambda sample: sample.filepath

        for key_fcn in (None, filepath_fcn):
            d1 = dataset1.clone()
            d1.merge_samples(dataset2, skip_existing=True, key_fcn=key_fcn)

            fields1 = set(dataset1.get_frame_field_schema().keys())
            fields2 = set(d1.get_frame_field_schema().keys())
            new_fields = fields2 - fields1

            self.assertEqual(len(d1), 3)
            for s1, s2 in zip(dataset1, d1):
                for f1, f2 in zip(s1.frames.values(), s2.frames.values()):
                    for field in fields1:
                        self.assertEqual(f1[field], f2[field])

                    for field in new_fields:
                        self.assertIsNone(f2[field])

        for key_fcn in (None, filepath_fcn):
            d2 = dataset1.clone()
            d2.merge_samples(dataset2, insert_new=False, key_fcn=key_fcn)

            self.assertEqual(len(d2), len(dataset1))

        for key_fcn in (None, filepath_fcn):
            with self.assertRaises(ValueError):
                d3 = dataset1.clone()
                d3.merge_samples(
                    dataset2, expand_schema=False, key_fcn=key_fcn
                )

        for key_fcn in (None, filepath_fcn):
            d3 = dataset1.clone()
            d3.merge_samples(
                dataset2, merge_lists=False, overwrite=True, key_fcn=key_fcn
            )

            self.assertListEqual(
                d3.values("frames.hello"),
                [[], [None, "world", "bar", "world", "bar"], []],
            )
            self.assertListEqual(
                d3.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["COMMON", "foo", "bar"],
                        ["hi", "there"],
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )
            self.assertListEqual(
                d3.values("frames.predictions1.detections.label"),
                [
                    [],
                    [None, ["hello", "world"], ["hello", "world"], None, None],
                    [],
                ],
            )
            self.assertListEqual(
                d3.values("frames.predictions2.detections.label"),
                [[], [None, None, ["foo", "bar"], None, ["foo", "bar"]], []],
            )

        for key_fcn in (None, filepath_fcn):
            d4 = dataset1.clone()
            d4.merge_samples(
                dataset2, merge_lists=False, overwrite=False, key_fcn=key_fcn
            )

            self.assertListEqual(
                d4.values("frames.hello"),
                [[], [None, "world", "world", "world", "bar"], []],
            )
            self.assertListEqual(
                d4.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "common"],
                        ["hi", "there"],
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )
            self.assertListEqual(
                d4.values("frames.predictions1.detections.label"),
                [
                    [],
                    [None, ["hello", "world"], ["hello", "world"], None, None],
                    [],
                ],
            )
            self.assertListEqual(
                d4.values("frames.predictions2.detections.label"),
                [[], [None, None, ["foo", "bar"], None, ["foo", "bar"]], []],
            )

        for key_fcn in (None, filepath_fcn):
            d5 = dataset1.clone()
            d5.merge_samples(dataset2, fields="frames.hello", key_fcn=key_fcn)

            # ensures documents are valid
            for sample in d5:
                self.assertIsNotNone(sample.id)
                for frame in sample.frames.values():
                    self.assertIsNotNone(frame.id)

            self.assertNotIn("predictions2", d5.get_frame_field_schema())
            self.assertListEqual(
                d5.values("frames.hello"),
                [[], [None, "world", "bar", "world", "bar"], []],
            )
            self.assertListEqual(
                d5.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "common"],
                        ["hi", "there"],
                        None,
                    ],
                    [],
                ],
            )

        for key_fcn in (None, filepath_fcn):
            d6 = dataset1.clone()
            d6.merge_samples(
                dataset2,
                omit_fields=["frames.ground_truth", "frames.predictions2"],
                key_fcn=key_fcn,
            )

            # ensures documents are valid
            for sample in d6:
                self.assertIsNotNone(sample.id)
                for frame in sample.frames.values():
                    self.assertIsNotNone(frame.id)

            self.assertNotIn("predictions2", d6.get_frame_field_schema())
            self.assertListEqual(
                d6.values("frames.hello"),
                [[], [None, "world", "bar", "world", "bar"], []],
            )
            self.assertListEqual(
                d6.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "common"],
                        ["hi", "there"],
                        None,
                    ],
                    [],
                ],
            )

        for key_fcn in (None, filepath_fcn):
            d7 = dataset1.clone()
            d7.merge_samples(
                dataset2, merge_lists=False, overwrite=True, key_fcn=key_fcn
            )

            self.assertListEqual(
                d7.values("frames.hello"),
                [[], [None, "world", "bar", "world", "bar"], []],
            )
            self.assertListEqual(
                d7.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["COMMON", "foo", "bar"],
                        ["hi", "there"],
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )

        for key_fcn in (None, filepath_fcn):
            d8 = dataset1.clone()
            d8.merge_samples(dataset2, key_fcn=key_fcn)

            self.assertListEqual(
                d8.values("frames.hello"),
                [[], [None, "world", "bar", "world", "bar"], []],
            )
            self.assertListEqual(
                d8.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "COMMON", "foo", "bar"],
                        ["hi", "there"],
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )
            self.assertListEqual(
                d8.values("frames.predictions1.detections.label"),
                [
                    [],
                    [None, ["hello", "world"], ["hello", "world"], None, None],
                    [],
                ],
            )
            self.assertListEqual(
                d8.values("frames.predictions2.detections.label"),
                [[], [None, None, ["foo", "bar"], None, ["foo", "bar"]], []],
            )

        for key_fcn in (None, filepath_fcn):
            d9 = dataset1.clone()
            d9.merge_samples(dataset2, overwrite=False, key_fcn=key_fcn)

            self.assertListEqual(
                d9.values("frames.hello"),
                [[], [None, "world", "world", "world", "bar"], []],
            )
            self.assertListEqual(
                d9.values("frames.ground_truth.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "common", "foo", "bar"],
                        ["hi", "there"],
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )
            self.assertListEqual(
                d9.values("frames.predictions1.detections.label"),
                [
                    [],
                    [None, ["hello", "world"], ["hello", "world"], None, None],
                    [],
                ],
            )
            self.assertListEqual(
                d9.values("frames.predictions2.detections.label"),
                [[], [None, None, ["foo", "bar"], None, ["foo", "bar"]], []],
            )

        for key_fcn in (None, filepath_fcn):
            d10 = dataset1.clone()
            d10.merge_samples(
                dataset2,
                fields={
                    "frames.hello": "frames.hello2",
                    "frames.predictions2": "frames.predictions1",
                },
                key_fcn=key_fcn,
            )

            d10_frame_schema = d10.get_frame_field_schema()
            self.assertIn("hello", d10_frame_schema)
            self.assertIn("hello2", d10_frame_schema)
            self.assertIn("predictions1", d10_frame_schema)
            self.assertNotIn("predictions2", d10_frame_schema)

            self.assertListEqual(
                d10.values("frames.hello"),
                [[], [None, "world", "world", "world", None], []],
            )
            self.assertListEqual(
                d10.values("frames.hello2"),
                [[], [None, None, "bar", None, "bar"], []],
            )
            self.assertListEqual(
                d10.values("frames.predictions1.detections.label"),
                [
                    [],
                    [
                        None,
                        ["hello", "world"],
                        ["hello", "world", "foo", "bar"],
                        None,
                        ["foo", "bar"],
                    ],
                    [],
                ],
            )

    @drop_datasets
    def test_to_frames(self):
        dataset = fo.Dataset()

        sample1 = fo.Sample(
            filepath="video.mp4",
            metadata=fo.VideoMetadata(total_frame_count=4),
            tags=["test"],
            weather="sunny",
        )
        sample1.frames[1] = fo.Frame(hello="world")
        sample1.frames[2] = fo.Frame(
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="cat"),
                    fo.Detection(label="dog"),
                ]
            )
        )
        sample1.frames[3] = fo.Frame(hello="goodbye")

        sample2 = fo.Sample(
            filepath="video.mp4",
            metadata=fo.VideoMetadata(total_frame_count=5),
            tags=["test"],
            weather="cloudy",
        )
        sample2.frames[1] = fo.Frame(
            hello="goodbye",
            ground_truth=fo.Detections(
                detections=[
                    fo.Detection(label="dog"),
                    fo.Detection(label="rabbit"),
                ]
            ),
        )
        sample2.frames[3] = fo.Frame()
        sample2.frames[5] = fo.Frame(hello="there")

        dataset.add_samples([sample1, sample2])

        view = dataset.to_frames(config={"sample_frames": False})

        self.assertFalse("weather" in view.get_field_schema())
        self.assertTrue("hello" in view.get_field_schema())
        self.assertTrue("ground_truth" in view.get_field_schema())
        self.assertEqual(len(view), 9)
        self.assertDictEqual(dataset.count_sample_tags(), {"test": 2})
        self.assertDictEqual(view.count_sample_tags(), {"test": 9})

        view.tag_samples("foo")

        self.assertEqual(view.count_sample_tags()["foo"], 9)
        self.assertNotIn("foo", dataset.count_sample_tags())
        self.assertNotIn("tags", dataset.get_frame_field_schema())

        view.untag_samples("foo")

        self.assertNotIn("foo", view.count_sample_tags())

        view.tag_labels("test")

        self.assertDictEqual(view.count_label_tags(), {"test": 4})
        self.assertDictEqual(dataset.count_label_tags(), {"test": 4})

        view.select_labels(tags="test").untag_labels("test")

        self.assertDictEqual(view.count_label_tags(), {})
        self.assertDictEqual(dataset.count_label_tags(), {})

        view2 = view.skip(4).set_field(
            "ground_truth.detections.label", F("label").upper()
        )

        self.assertDictEqual(
            view.count_values("ground_truth.detections.label"),
            {"cat": 1, "dog": 2, "rabbit": 1},
        )
        self.assertDictEqual(
            view2.count_values("ground_truth.detections.label"),
            {"DOG": 1, "RABBIT": 1},
        )
        self.assertDictEqual(
            dataset.count_values("frames.ground_truth.detections.label"),
            {"cat": 1, "dog": 2, "rabbit": 1},
        )

        view2.save()

        self.assertEqual(len(view), 5)
        self.assertEqual(dataset.values(F("frames").length()), [0, 5])
        self.assertDictEqual(
            view.count_values("ground_truth.detections.label"),
            {"DOG": 1, "RABBIT": 1},
        )
        self.assertDictEqual(
            dataset.count_values("frames.ground_truth.detections.label"),
            {"DOG": 1, "RABBIT": 1},
        )
        self.assertIsNotNone(view.first().frame_id)
        self.assertIsNotNone(dataset.last().frames.first().id)

        sample = view.exclude_fields("ground_truth").first()

        sample["foo"] = "bar"
        sample.save()

        self.assertIn("foo", view.get_field_schema())
        self.assertIn("foo", dataset.get_frame_field_schema())
        self.assertIn("ground_truth", view.get_field_schema())
        self.assertIn("ground_truth", dataset.get_frame_field_schema())
        self.assertEqual(view.count_values("foo")["bar"], 1)
        self.assertEqual(dataset.count_values("frames.foo")["bar"], 1)
        self.assertDictEqual(
            view.count_values("ground_truth.detections.label"),
            {"DOG": 1, "RABBIT": 1},
        )
        self.assertDictEqual(
            dataset.count_values("frames.ground_truth.detections.label"),
            {"DOG": 1, "RABBIT": 1},
        )

        dataset.untag_samples("test")
        view.reload()

        self.assertEqual(dataset.count_sample_tags(), {})
        self.assertEqual(view.count_sample_tags(), {})


if __name__ == "__main__":
    fo.config.show_progress_bars = False
    unittest.main(verbosity=2)
