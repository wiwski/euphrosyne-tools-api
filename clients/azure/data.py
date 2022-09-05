import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator, Literal, Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.file.models import FilePermissions
from azure.storage.file.sharedaccesssignature import FileSharedAccessSignature
from azure.storage.fileshare import (
    CorsRule,
    ShareDirectoryClient,
    ShareFileClient,
    ShareServiceClient,
)
from dotenv import load_dotenv
from pydantic import BaseModel

from auth import User

from ._storage import BaseStorageAzureClient

load_dotenv()


RunDataTypeType = Literal["processed_data", "raw_data"]


class RunDataNotFound(Exception):
    pass


class ProjectDocumentsNotFound(Exception):
    pass


class IncorrectDataFilePath(Exception):
    def __init__(self, message: str, *args: object):
        self.message = message
        super().__init__(*args)


class ProjectFile(BaseModel):
    name: str
    last_modified: Optional[datetime]
    size: int
    path: Optional[str]


class DataAzureClient(BaseStorageAzureClient):
    def __init__(self):
        super().__init__()
        self._file_shared_access_signature = FileSharedAccessSignature(
            account_name=self.storage_account_name, account_key=self._storage_key
        )

    def get_project_documents(
        self,
        project_name: str,
    ) -> list[ProjectFile]:
        dir_path = os.path.join(_get_projects_path(), project_name, "documents")
        files = self._list_files_recursive(dir_path, fetch_detailed_information=True)
        try:
            return list(files)
        except ResourceNotFoundError as error:
            raise ProjectDocumentsNotFound from error

    def get_run_files(
        self,
        project_name: str,
        run_name: str,
        data_type: RunDataTypeType,
    ) -> list[ProjectFile]:
        """Fetches run data files from Fileshare.
        Specify `data_type` to get either 'raw_data' or 'processed_data'.
        """
        projects_path_prefix = _get_projects_path()
        dir_path = os.path.join(
            projects_path_prefix, project_name, "runs", run_name, data_type
        )
        files = self._list_files_recursive(dir_path)
        try:
            return list(files)
        except ResourceNotFoundError as error:
            raise RunDataNotFound from error

    def generate_run_data_sas_url(
        self,
        dir_path: str,
        file_name: str,
        is_admin: bool,
    ):
        """Generate URL with Shared Access Signature to manage run data in an
        Azure Fileshare. Regular users can read. Admins can also write, create & delete.
        """
        permission = FilePermissions(
            read=True, create=is_admin, write=is_admin, delete=is_admin
        )
        return self._generate_sas_url(dir_path, file_name, permission)

    def generate_project_documents_upload_sas_url(
        self, project_name: str, file_name: str
    ):
        """Generate URL with Shared Access Signature to manage project documents in
        an Azure Fileshare. Permission are write & create. To download and delete use
        generate_project_documents_sas_url.
        """
        dir_path = os.path.join(_get_projects_path(), project_name, "documents")
        permission = FilePermissions(read=False, create=True, write=True, delete=False)
        return self._generate_sas_url(dir_path, file_name, permission)

    def generate_project_documents_sas_url(self, dir_path: str, file_name: str):
        """Generate URL with Shared Access Signature to manage project documents in
        an Azure Fileshare. Permission are read & delete. To upload a document use
        generate_project_documents_upload_sas_url.
        """
        permission = FilePermissions(read=True, create=False, write=False, delete=True)
        return self._generate_sas_url(dir_path, file_name, permission)

    def _generate_sas_url(
        self,
        dir_path: str,
        file_name: str,
        permission: FilePermissions,
    ) -> str:
        """Generate a signed URL (Shared Access Signature) that can be used
        to perform authenticated operations on a file in an Azure Fileshare.
        """
        share_name = os.environ["AZURE_STORAGE_FILESHARE"]
        sas_params = self._file_shared_access_signature.generate_file(
            share_name=share_name,
            directory_name=dir_path,
            file_name=file_name,
            permission=permission,
            expiry=datetime.utcnow() + timedelta(minutes=5),
            start=datetime.utcnow(),
        )
        # pylint: disable=line-too-long
        return f"https://{self.storage_account_name}.file.core.windows.net/{share_name}/{dir_path}/{file_name}?{sas_params}"

    def set_fileshare_cors_policy(self, allowed_origins: str):
        """Set Cross-Origin Resource Sharing (CORS) for Azure Fileshare.

        Arguments:
        allowed_origins -- A string representing allowed origins as specified here :
            https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Access-Control-Allow-Origin
            Multiple origins can be specified by separating them with commas.
        """
        file_service = ShareServiceClient.from_connection_string(
            self._storage_connection_string
        )
        file_service.set_service_properties(
            cors=[
                CorsRule(
                    allowed_origins=allowed_origins.split(","),
                    allowed_methods=["DELETE", "GET", "HEAD", "POST", "OPTIONS", "PUT"],
                    allowed_headers=[
                        "x-ms-content-length",
                        "x-ms-type",
                        "x-ms-version",
                        "x-ms-write",
                        "x-ms-range",
                        "content-type",
                    ],
                )
            ]
        )

    def _list_files_recursive(
        self, dir_path: str, fetch_detailed_information: bool = False
    ) -> Generator[ProjectFile, None, None]:
        """
        List files from FileShare on Azure Storage Account.

        Parameters
        ----------
        dir_path: str
            Directory path to list files from.
        recursive: bool
            Specifies whether to list files recursively.
        fetch_detailed_information: bool
            If True will make a request for each file to get more metadata
            about it.

        Returns
        -------
        files_list: Iterator[azure_client.ProjectFile]
            List of file properties from FileShare.

        Notes
        -----
        This method only lists files, ignoring empty directories.

        References
        ----------
        .. [1] Credit to joao8tunes :
            https://stackoverflow.com/questions/66532170/azure-file-share-recursive-directory-search-like-os-walk
        .. [2] Recursive files listing: https://stackoverflow.com/a/66543222/16109419
        """
        share_name = os.environ["AZURE_STORAGE_FILESHARE"]

        dir_client = ShareDirectoryClient.from_connection_string(
            conn_str=self._storage_connection_string,
            share_name=share_name,
            directory_path=dir_path,
        )

        # Listing files from current directory path:
        for file in dir_client.list_directories_and_files():
            name, is_directory = file["name"], file["is_directory"]
            path = os.path.join(dir_path, name)

            if is_directory:
                # Listing files recursively:
                childrens = self._list_files_recursive(
                    dir_path=path,
                )

                for child in childrens:
                    yield child
            else:
                if fetch_detailed_information:
                    file_client = ShareFileClient.from_connection_string(
                        conn_str=self._storage_connection_string,
                        share_name=share_name,
                        file_path=path,
                    )
                    yield ProjectFile.parse_obj(file_client.get_file_properties())
                else:
                    yield ProjectFile.parse_obj({**file, "path": path})


def validate_run_data_file_path(path: Path, current_user: User):
    if not re.match(
        rf"^{_get_projects_path()}\/[\w\- ]+\/runs\/[\w\- ]+\/(raw_data|processed_data)\/",
        str(path),
    ):
        # pylint: disable=line-too-long
        raise IncorrectDataFilePath(
            "path must start with {projects_path_prefix}/<project_name>/runs/<run_name>/(processed_data|raw_data)/"
        )
    _validate_project_file_path(path, current_user)


def validate_project_document_file_path(path: Path, current_user: User):
    if not re.match(rf"^{_get_projects_path()}\/[\w\- ]+\/documents", str(path)):
        raise IncorrectDataFilePath(
            "path must start with {projects_path_prefix}/<project_name>/documents/"
        )
    _validate_project_file_path(path, current_user)


def _get_projects_path():
    return os.getenv("AZURE_STORAGE_PROJECTS_LOCATION_PREFIX", "")


def _validate_project_file_path(path: Path, current_user: User):
    """Given a path, validate the path is valid for project data and the user has
    permission to access it.
    """
    projects_path_prefix = _get_projects_path()
    path_without_prefix = Path(str(path).replace(projects_path_prefix + "/", "", 1))
    project_name = path_without_prefix.parts[0]
    if not current_user.has_project(project_name) and not current_user.is_admin:
        raise IncorrectDataFilePath(f"user is not part of project {project_name}")