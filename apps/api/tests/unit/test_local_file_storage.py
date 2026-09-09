from __future__ import annotations

from trinol.platform.file_storage.local import LocalFileStorage


async def test_put_get_round_trips_bytes(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.put("org/file.png", b"hello world", content_type="image/png")

    assert await storage.get("org/file.png") == b"hello world"


async def test_exists_reflects_put_and_delete(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path)

    assert await storage.exists("org/file.png") is False

    await storage.put("org/file.png", b"data", content_type="image/png")
    assert await storage.exists("org/file.png") is True

    await storage.delete("org/file.png")
    assert await storage.exists("org/file.png") is False


async def test_delete_is_idempotent_for_a_missing_key(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path)
    # Should not raise even though the key was never written.
    await storage.delete("org/never-existed.png")


async def test_keys_with_nested_org_prefix_create_subdirectories(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.put("11111111-1111-1111-1111-111111111111/f.png", b"x", content_type="image/png")

    assert (tmp_path / "11111111-1111-1111-1111-111111111111" / "f.png").is_file()
