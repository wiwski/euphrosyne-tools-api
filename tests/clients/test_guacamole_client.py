# pylint: disable=protected-access, no-member, redefined-outer-name

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from clients import VMSizes
from clients.guacamole import (
    GuacamoleClient,
    GuacamoleConnectionNotFound,
    GuacamoleHttpError,
    get_password_for_username,
)
from clients.guacamole.models import GuacamoleConnectionsAndGroupsResponse

from ..mocks import (
    GUACAMOLE_CONNECTION_LIST_RESPONSE,
    GUACAMOLE_CONNECTIONS_AND_GROUPS_RESPONSE,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GUACAMOLE_SECRET_KEY", "secret")
    monkeypatch.setenv("GUACAMOLE_ROOT_URL", "https://local.guacamole")
    return GuacamoleClient()


def test_get_token(client: GuacamoleClient):
    token_response = MagicMock(
        json=MagicMock(return_value={"authToken": "token", "username": "admin"})
    )
    with patch("clients.guacamole.client.requests") as requests_mock:
        requests_mock.post.return_value = token_response
        assert client._get_token(username="1", password="abc") == "token"


@patch.dict(
    os.environ,
    {"GUACAMOLE_ADMIN_USERNAME": "username", "GUACAMOLE_ADMIN_PASSWORD": "password"},
)
@patch("clients.guacamole.client.requests", MagicMock)
def test_get_admin_token(client: GuacamoleClient):
    with patch.object(client, "_get_token") as get_token_mock:
        client._get_admin_token()
        get_token_mock.assert_called_with("username", "password")


def test_get_connection_by_name_retrieves_connection(client: GuacamoleClient):
    response = MagicMock(
        json=MagicMock(return_value=GUACAMOLE_CONNECTION_LIST_RESPONSE)
    )
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.get.return_value = response
            assert client.get_connection_by_name("test-02") == "2"


def test_get_connection_by_name_raises_when_no_connection(client: GuacamoleClient):
    response = MagicMock(
        json=MagicMock(return_value=GUACAMOLE_CONNECTION_LIST_RESPONSE)
    )
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.get.return_value = response
            with pytest.raises(GuacamoleConnectionNotFound):
                client.get_connection_by_name("unknown connection")


def test_create_connection_with_proper_parameters(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            client.create_connection(
                "name", "ip_address", "username", "password", "port"
            )
            post_data = requests_mock.post.call_args[1]["json"]
            assert post_data["parentIdentifier"] == "1"
            assert post_data["name"] == "name"
            assert post_data["protocol"] == "rdp"
            assert post_data["parameters"]["port"] == "port"
            assert post_data["parameters"]["hostname"] == "ip_address"
            assert post_data["parameters"]["username"] == "username"
            assert post_data["parameters"]["password"] == "password"
            assert post_data["parameters"]["drive-name"] == "Downloads"
            assert (
                post_data["parameters"]["drive-path"] == "/filetransfer/downloads/name"
            )


def test_create_connection_for_imagery(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            client.create_connection(
                "name",
                "ip_address",
                "username",
                "password",
                "port",
                vm_size=VMSizes.IMAGERY,
            )
            post_data = requests_mock.post.call_args[1]["json"]
            assert post_data["parentIdentifier"] == "2"


def test_assign_user_to_connection_with_proper_parameters(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            client.assign_user_to_connection("connection_id", "username")

            url, data = requests_mock.patch.call_args
            patch_data = data["json"]

            assert "/api/session/data/mysql/users/username/permissions" in url[0]
            assert patch_data[0]["path"] == "/connectionPermissions/connection_id"


def test_create_user_if_absent_when_user_absent(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.get.return_value = MagicMock(ok=False)
            client.create_user_if_absent("username")

            requests_mock.post.assert_called_once()
            post_data = requests_mock.post.call_args[1]["json"]
            assert post_data["username"] == "username"
            assert post_data["password"]


def test_create_user_if_absent_when_user_exists(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.get.return_value = MagicMock(ok=True)
            client.create_user_if_absent("username")

            requests_mock.post.assert_not_called()


def test_delete_connection_with_proper_parameters(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch.object(client, "get_connection_by_name") as get_conn_by_name_mock:
            with patch("clients.guacamole.client.requests") as requests_mock:
                get_conn_by_name_mock.return_value = 1
                client.delete_connection("connection")
                url, _ = requests_mock.delete.call_args
                assert "/api/session/data/mysql/connections/1" in url[0]


def test_delete_connection_raises_proper_error_on_404(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.delete.return_value = MagicMock(ok=False, status_code=404)
            with pytest.raises(GuacamoleConnectionNotFound):
                client.delete_connection("connection")


def test_delete_connection_raises_proper_error_on_http_error(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch.object(client, "get_connection_by_name"):
            with patch("clients.guacamole.client.requests") as requests_mock:
                requests_mock.delete.return_value = MagicMock(ok=False, status_code=500)
                with pytest.raises(GuacamoleHttpError):
                    client.delete_connection("connection")


def test_generate_connection_link(client: GuacamoleClient):
    with patch.object(client, "_get_token"):
        url = client.generate_connection_link("connection_id", "user_id")
        assert "/#/client/Y29ubmVjdGlvbl9pZABjAG15c3Fs" in url


def test_get_password_for_username():
    password = get_password_for_username("username", "key")
    assert (
        password == "29fb5cb8efb57c7e696d27cd759b66c290b1246e44a32ddfb970ba0fea9245c5"
    )


def test_get_connections_and_groups(client: GuacamoleClient):
    response = MagicMock(
        json=MagicMock(return_value=GUACAMOLE_CONNECTIONS_AND_GROUPS_RESPONSE)
    )
    with patch.object(client, "_get_admin_token"):
        with patch("clients.guacamole.client.requests") as requests_mock:
            requests_mock.get.return_value = response
            data = client.get_connections_and_groups()

            assert isinstance(data, GuacamoleConnectionsAndGroupsResponse)


def test_vm_to_shutdown(client: GuacamoleClient):
    with patch.object(client, "_get_admin_token"):
        with patch.object(
            client,
            "get_connections_and_groups",
            return_value=GuacamoleConnectionsAndGroupsResponse.parse_obj(
                GUACAMOLE_CONNECTIONS_AND_GROUPS_RESPONSE
            ),
        ):
            fake_now = datetime.fromtimestamp(
                1662369688000 / 1000, tz=timezone.utc
            ) + timedelta(minutes=35)

            projects_to_shutdown = client.get_vm_to_shutdown(from_date=fake_now)
            assert projects_to_shutdown == []

            projects_to_shutdown = client.get_vm_to_shutdown(
                skip_groups=["default"], from_date=fake_now
            )
            assert projects_to_shutdown == ["update-setup"]

            fake_now_before_shutdown = datetime.fromtimestamp(
                1662369688000 / 1000, tz=timezone.utc
            ) + timedelta(minutes=20)
            projects_to_shutdown = client.get_vm_to_shutdown(
                skip_groups=["default"], from_date=fake_now_before_shutdown
            )
            assert projects_to_shutdown == []

            projects_to_shutdown = client.get_vm_to_shutdown(
                skip_groups=["default"],
                from_date=fake_now_before_shutdown,
                kill_no_connection=True,
            )
            assert projects_to_shutdown == ["update-setup-clone"]
