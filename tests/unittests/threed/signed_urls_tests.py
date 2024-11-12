import unittest
from unittest import mock

from fiftyone.core.threed import GltfMesh, PointCloud, Scene
from fiftyone.server.routes import fo3d_resolver, signed_url


class TestSignedUrlsFo3d(unittest.TestCase):
    def test_absolute_local_paths(self):
        # Test that absolute local paths are not modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "/path/to/gltf.gltf"))
        scene.add(PointCloud("pcd", "/path/to/pcd.pcd"))

        fo3d_resolver.resolve_urls_for_scene(scene)

        self.assertEqual(
            scene.children[0].gltf_path,
            "/path/to/gltf.gltf",
        )
        self.assertEqual(
            scene.children[1].pcd_path,
            "/path/to/pcd.pcd",
        )

    def test_relative_local_paths(self):
        # Test that relative paths are modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "path/to/gltf.gltf"))
        scene.add(PointCloud("pcd", "path/to/pcd.pcd"))

        fo3d_resolver.resolve_urls_for_scene(scene, root="/path/to/root")

        self.assertEqual(scene.children[0].gltf_path, "path/to/gltf.gltf")
        self.assertEqual(scene.children[1].pcd_path, "path/to/pcd.pcd")

    def test_relative_cloud_paths(self):
        # Test that relative paths are modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "path/to/gltf.gltf"))

        with mock.patch.object(
            fo3d_resolver.media_cache, "get_url"
        ) as get_url_mock:
            fo3d_resolver.resolve_urls_for_scene(
                scene, root="s3://bucket/root"
            )
            get_url_mock.assert_called_with(
                "s3://bucket/root/path/to/gltf.gltf",
                method="GET",
            )

            self.assertEqual(
                scene.children[0]._pre_transformed_gltf_path,
                get_url_mock.return_value,
            )

    def test_relative_cloud_paths_with_traversal(self):
        # Test that relative paths are modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "../path/to/gltf.gltf"))

        with mock.patch.object(
            fo3d_resolver.media_cache, "get_url"
        ) as get_url_mock:

            fo3d_resolver.resolve_urls_for_scene(
                scene, root="s3://bucket/root/test"
            )
            get_url_mock.assert_called_with(
                "s3://bucket/root/path/to/gltf.gltf",
                method="GET",
            )

            self.assertEqual(
                scene.children[0]._pre_transformed_gltf_path,
                get_url_mock.return_value,
            )

    def test_relative_cloud_paths_with_traversal(self):
        # Test that relative paths are modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "../path/to/gltf.gltf"))

        with mock.patch.object(
            fo3d_resolver.fos, "get_file_system"
        ) as get_file_system_mock:
            with mock.patch.object(
                fo3d_resolver.media_cache, "get_url"
            ) as get_url_mock:
                get_file_system_mock.side_effect = [
                    fo3d_resolver.fos.FileSystem.LOCAL,
                    fo3d_resolver.fos.FileSystem.S3,
                ]

                fo3d_resolver.resolve_urls_for_scene(
                    scene, root="s3://bucket/root/test"
                )
                get_url_mock.assert_called_with(
                    "s3://bucket/root/path/to/gltf.gltf",
                    method="GET",
                )

                self.assertEqual(
                    scene.children[0]._pre_transformed_gltf_path,
                    get_url_mock.return_value,
                )

    def test_absolute_cloud_paths_with_root(self):
        # Test that absolute cloud paths with root are resolved
        scene = Scene()
        scene.add(GltfMesh("gltf", "s3://bucket1/path/to/gltf.gltf"))

        with mock.patch.object(
            fo3d_resolver.fos, "get_file_system"
        ) as get_file_system_mock:
            with mock.patch.object(
                fo3d_resolver.media_cache, "get_url"
            ) as get_url_mock:
                get_file_system_mock.return_value = (
                    fo3d_resolver.fos.FileSystem.S3
                )

                fo3d_resolver.resolve_urls_for_scene(
                    scene, root="s3://bucket/root"
                )
                get_url_mock.assert_called_with(
                    "s3://bucket1/path/to/gltf.gltf",
                    method="GET",
                )

                self.assertEqual(
                    scene.children[0]._pre_transformed_gltf_path,
                    get_url_mock.return_value,
                )

    def test_absolute_cloud_paths_with_no_root(self):
        # Test that absolute cloud paths with no root are resolved
        scene = Scene()
        scene.add(GltfMesh("gltf", "s3://bucket1/path/to/gltf.gltf"))

        with mock.patch.object(
            fo3d_resolver.fos, "get_file_system"
        ) as get_file_system_mock:
            with mock.patch.object(
                fo3d_resolver.media_cache, "get_url"
            ) as get_url_mock:
                get_file_system_mock.return_value = (
                    fo3d_resolver.fos.FileSystem.S3
                )

                fo3d_resolver.resolve_urls_for_scene(
                    scene, root="s3://bucket/root"
                )
                get_url_mock.assert_called_with(
                    "s3://bucket1/path/to/gltf.gltf",
                    method="GET",
                )

                self.assertEqual(
                    scene.children[0]._pre_transformed_gltf_path,
                    get_url_mock.return_value,
                )

    def test_http_paths_with_root(self):
        # Test that http paths with root are not modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "http://example.com/gltf.gltf"))
        scene.add(PointCloud("pcd", "http://example.com/pcd.pcd"))

        fo3d_resolver.resolve_urls_for_scene(scene, root="s3://bucket/root")

        self.assertEqual(
            scene.children[0].gltf_path,
            "http://example.com/gltf.gltf",
        )
        self.assertEqual(
            scene.children[1].pcd_path,
            "http://example.com/pcd.pcd",
        )

    def test_http_paths_with_no_root(self):
        # Test that http paths with no root are not modified
        scene = Scene()
        scene.add(GltfMesh("gltf", "http://example.com/gltf.gltf"))
        scene.add(PointCloud("pcd", "http://example.com/pcd.pcd"))

        fo3d_resolver.resolve_urls_for_scene(scene)

        self.assertEqual(
            scene.children[0].gltf_path,
            "http://example.com/gltf.gltf",
        )
        self.assertEqual(
            scene.children[1].pcd_path,
            "http://example.com/pcd.pcd",
        )


class TestGeneralSignedUrls(unittest.TestCase):
    def test_absolute_local_paths(self):
        # Test that absolute local paths are not modified
        self.assertEqual(
            signed_url.get_signed_url("/path/to/file"), "/path/to/file"
        )

    def test_relative_local_paths(self):
        # Test that relative local paths are not modified
        self.assertEqual(
            signed_url.get_signed_url("path/to/file"), "path/to/file"
        )

    def test_http_paths(self):
        # Test that http paths are not modified
        self.assertEqual(
            signed_url.get_signed_url("http://example.com/file"),
            "http://example.com/file",
        )

    def test_s3_paths(self):
        # Test that s3 paths are signed
        with mock.patch.object(
            signed_url.fos, "get_file_system"
        ) as get_file_system_mock:
            with mock.patch.object(
                signed_url.media_cache, "get_url"
            ) as get_url_mock:
                get_file_system_mock.return_value = (
                    signed_url.fos.FileSystem.S3
                )

                signed_url.get_signed_url("s3://bucket/path/to/file")
                get_url_mock.assert_called_with(
                    "s3://bucket/path/to/file",
                    method="GET",
                    hours=24,
                )
