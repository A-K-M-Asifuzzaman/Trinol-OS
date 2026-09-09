from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from trinol.platform.file_storage.s3 import S3FileStorage


def _make_storage(mock_client: MagicMock) -> S3FileStorage:
    with patch("trinol.platform.file_storage.s3.boto3.client", return_value=mock_client):
        return S3FileStorage(
            bucket="test-bucket",
            endpoint_url="http://localhost:9000",
            access_key_id="key",
            secret_access_key="secret",
            region="us-east-1",
        )


async def test_put_calls_put_object_with_bucket_key_and_content_type() -> None:
    mock_client = MagicMock()
    storage = _make_storage(mock_client)

    await storage.put("org/file.png", b"data", content_type="image/png")

    mock_client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="org/file.png", Body=b"data", ContentType="image/png"
    )


async def test_get_returns_the_bodys_bytes() -> None:
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": io.BytesIO(b"hello")}
    storage = _make_storage(mock_client)

    result = await storage.get("org/file.png")

    assert result == b"hello"
    mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="org/file.png")


async def test_delete_calls_delete_object() -> None:
    mock_client = MagicMock()
    storage = _make_storage(mock_client)

    await storage.delete("org/file.png")

    mock_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="org/file.png")


async def test_exists_returns_true_when_head_object_succeeds() -> None:
    mock_client = MagicMock()
    storage = _make_storage(mock_client)

    assert await storage.exists("org/file.png") is True
    mock_client.head_object.assert_called_once_with(Bucket="test-bucket", Key="org/file.png")


async def test_exists_returns_false_on_404() -> None:
    mock_client = MagicMock()
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )
    storage = _make_storage(mock_client)

    assert await storage.exists("org/file.png") is False


async def test_exists_reraises_other_client_errors() -> None:
    mock_client = MagicMock()
    mock_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Internal Error"}}, "HeadObject"
    )
    storage = _make_storage(mock_client)

    with pytest.raises(ClientError):
        await storage.exists("org/file.png")
