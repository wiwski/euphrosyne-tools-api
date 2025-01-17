#!/usr/bin/env python3
"""
Create a Azure VM and a Guacamole connection
"""
import argparse

from clients.azure import VMAzureClient
from clients.guacamole import GuacamoleClient

from . import get_logger

logger = get_logger(__name__)


def create_vm():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--project",
        dest="project_name",
        help="Project name related to the VM to create.",
        required=True,
    )
    parser.add_argument(
        "-v",
        "--version",
        help="Version of the Azure Template Spec to use",
    )
    args = parser.parse_args()

    azure_client = VMAzureClient()

    logger.info("Deploying VM... This can take a while.")
    deployment = azure_client.deploy_vm(
        project_name=args.project_name, spec_version=args.version
    )
    if not deployment:
        logger.info("VM is already deployed.")
        return
    deployment_information = deployment.deployment_process.result()
    if deployment_information.properties.provisioning_state == "Succeeded":
        logger.info("VM deployed. Creating Guacamole connection...")
        GuacamoleClient().create_connection(
            name=deployment.project_name,
            ip_address=deployment_information.properties.outputs["privateIPVM"][
                "value"
            ],
            password=deployment.password,
            username=deployment.username,
        )
        logger.info("Guacamole connection created. Deleting Azure deployment...")
        azure_client.delete_deployment(deployment_information.name)
        logger.info("OK")
    else:
        logger.error("Deployment failed !")


if __name__ == "__main__":
    create_vm()
