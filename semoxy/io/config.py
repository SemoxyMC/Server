from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..sanicserver import Semoxy


class Config:
    """
    static class for managing configurations
    """
    SEMOXY_INSTANCE: Semoxy = None

    ATTR_KEYS = {
        "DB_PATH": ("dbPath", "data.db"),
        "SESSION_EXPIRATION": ("sessionExpiration", 7200),
        "VERSIONS": ("versions", {}),
        "MAX_RAM": ("maxRam", 2),
        "MONGO":  ("mongoDB", {}),
        "SERVER_DIR": ("serverDir", "./servers"),
        "ADDONS": ("addons", {}),
        "JAVA": ("javaSettings", {}),
        "PEPPER": ("pepper", "20 rndm pepper bytes"),
        "STATIC_IP": ("staticIP", "")
    }

    DB_PATH = "data.db"
    VERSIONS = {}
    SESSION_EXPIRATION = 7200
    MAX_RAM = 2
    MONGO = {}
    SERVER_DIR = "./servers"
    ADDONS = {}
    JAVA = {}
    PEPPER = ""
    STATIC_IP = ""

    @staticmethod
    def load(mcweb) -> None:
        """
        loads the config file and stores it's values as class attributes
        """
        Config.SEMOXY_INSTANCE = mcweb
        config_secret = Config.get_docker_secret("config")
        if config_secret:
            data = json.loads(config_secret)
        else:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.loads(f.read())

        for attr, key in Config.ATTR_KEYS.items():
            try:
                setattr(Config, attr, data[key[0]])
            except KeyError:
                setattr(Config, attr, key[1])

    @staticmethod
    def public_json():
        """
        returns the parts of the config that can be exposed to clients
        :return:
        """
        java_versions = {}
        for k, v in Config.JAVA["installations"].items():
            java_versions[k] = v["displayName"]
        return {
            "javaVersions": java_versions,
            "maxRam": Config.MAX_RAM,
            "publicIP": Config.SEMOXY_INSTANCE.public_ip
        }

    @staticmethod
    def get_docker_secret(key):
        """
        tries to access a docker secret
        :param key: the secret name
        :return: the value as string if the secret was found, else None
        """
        try:
            with open(f"/run/secrets/{key}", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
