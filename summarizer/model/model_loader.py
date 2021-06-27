import json
from typing import Optional
from os import path
import os
import pathlib
import logging
import torch
from transformers import LEDTokenizer, LEDForConditionalGeneration
from azureml.core.model import Model
from azureml.core import Workspace
from azureml.core.authentication import ServicePrincipalAuthentication, MsiAuthentication

MODEL_LOADER_CONFIG_JSON = 'model_loader_config.json'
CACHE = 'cache'

my_device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
logger = logging.getLogger(__name__)

default_model_name = 'led-large-16384-arxiv'
default_subscription = '091ac194-317f-4880-9f66-a9c23f42cb60'
default_resource_group = 'dev'
default_ml_workspace = 'ecb-dev'
default_model_version = 'None'


def load_model_names():
    logger.info('Getting existing model names from registry')
    cfg = read_config()
    spa = build_service_principal()
    ws = Workspace.get(subscription_id=cfg.get('subscription'),
                       resource_group=cfg.get('resource_group'),
                       name=cfg.get('workspace'),
                       auth=spa)
    models: list[Model] = Model.list(ws)
    return [f'{m.name}::{m.version}' for m in models]


def download_model_from_workspace(workspace: Workspace,
                                  model_name: str,
                                  target_dir: str,
                                  model_version: Optional[int] = None):
    aml_model = Model(workspace=workspace, name=model_name, version=model_version)
    model_path = aml_model.download(target_dir=target_dir, exist_ok=True)
    logger.info(f'Loaded model {aml_model.name} to {model_path}')
    return model_path


def read_config(base_dir: str = CACHE) -> dict:
    """
    This functions assembles a config dictionary of values required to connect to an Azure ML Workspace. The fct
    attempts to read the config from pvc first, accesses environment values afterwards, and finally falls back to hard
    coded default values.

    :return: a dictionary holding the values for ML model name, Azure subscription, Azure resource group, ML Workspace
    and model version.
    """
    cfg = None

    config_file = path.join(base_dir, MODEL_LOADER_CONFIG_JSON)
    if path.exists(config_file):
        logger.info(f'Found config file {config_file}. Loading cfg from disk...')
        with open(config_file, 'r') as json_file:
            cfg = json.load(json_file)

    if cfg is None:
        logger.info(f'No config file found. Loading cfg from env vars...')
        cfg = {
            "model_name": os.environ.get('MODEL_NAME') if os.environ.get('MODEL_NAME') else default_model_name,
            "subscription": os.environ.get('SUBSCRIPTION') if os.environ.get('SUBSCRIPTION') else default_subscription,
            "resource_group": os.environ.get('RESOURCE_GROUP')
            if os.environ.get('RESOURCE_GROUP') else default_resource_group,
            "workspace": os.environ.get('ML_WORKSPACE') if os.environ.get('ML_WORKSPACE') else default_ml_workspace,
            'model_version': os.environ.get('MODEL_VERSION') if os.environ.get('MODEL_VERSION') else default_model_version
        }
        if not path.exists(base_dir):
            pathlib.Path(base_dir).mkdir(parents=True)
        with open(config_file, 'w') as json_file:
            json.dump(cfg, json_file)
            logger.info(f'Stored config on disk at {config_file}')

    return cfg


# this can be improved
# https://docs.microsoft.com/en-us/azure/developer/python/azure-sdk-authenticate
def build_service_principal() -> ServicePrincipalAuthentication:
    return ServicePrincipalAuthentication(
        tenant_id=os.environ.get('TENANT_ID'),
        service_principal_id=os.environ.get('CLIENT_ID'),
        service_principal_password=os.environ.get('CLIENT_SECRET')
    )


def fetch_model(cfg: dict = None):
    auth = build_service_principal()
    download_path = path.join('.', CACHE)
    if cfg is None:
        cfg = read_config()
    model_version = cfg.get('model_version')
    target_dir = path.join(download_path, cfg['model_name'], model_version if model_version is not None else 'None')

    downloaded_model_path = path.join(target_dir, cfg.get('model_name'))
    if not path.exists(downloaded_model_path):
        ws = Workspace.get(subscription_id=cfg.get('subscription'),
                           resource_group=cfg.get('resource_group'),
                           name=cfg.get('workspace'),
                           auth=auth
                           )
        logger.info(f' Loading model from ml registry: {ws.name}')
        download_model_from_workspace(workspace=ws, model_name=cfg.get('model_name'), target_dir=target_dir)
        logger.info(f' Loaded model from ml registry and stored it: {downloaded_model_path}')
    else:
        logger.info('Loading model from local cache')

    model = LEDForConditionalGeneration.from_pretrained(downloaded_model_path)
    model.to(my_device)
    tokenizer = LEDTokenizer.from_pretrained(downloaded_model_path)
    return model, tokenizer
