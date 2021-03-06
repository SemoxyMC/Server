from __future__ import annotations

import secrets
import socket
from functools import wraps
from json import dumps as json_dumps
from os.path import split as split_path
from typing import Union, Tuple, Type
from urllib.parse import urlparse

import aiofiles
import aiohttp
import pydantic
from bson.objectid import ObjectId
from sanic.request import Request
from sanic.response import json, HTTPResponse

from semoxy.io.config import Config
from .io.regexes import Regexes


class APIError:
    ROOT_DISABLED = "root_disabled", 400
    INVALID_CREDENTIALS = "invalid_credentials", 401
    ALREADY_EXISTING = "already_existing", 400
    INVALID_NAME = "invalid_name", 400
    PORT_IN_USE = "port_in_use", 423
    INVALID_SORT_DIRECTION = "invalid_sort_direction", 400
    UNKNOWN = "unknown", 500
    INVALID_VERSION = "invalid_version", 400
    TOO_MUCH_RAM = "too_much_ram", 400
    INVALID_PORT_TYPE = "invalid_port_type", 400
    INVALID_PORT = "invalid_port", 400
    ILLEGAL_SERVER_NAME = "illegal_server_name", 400
    INVALID_JAVA_VERSION = "invalid_java_version", 400
    SERVER_VERSION_POST_INSTALL = "server_version_post_install", 500
    MISSING_VALUE = "missing_value", 400
    INVALID_SERVER = "invalid_server", 404
    INVALID_SERVER_STATUS = "invalid_server_status", 423
    UNAUTHENTICATED = "unauthenticated", 401
    NO_PERMISSION = "no_permission", 403
    INVALID_SESSION = "invalid_session", 401
    SESSION_EXPIRED = "session_expired", 401
    INVALID_PAYLOAD_SCHEMA = "invalid_payload_schema", 400


def json_error(error: Tuple[str, int], description: str, **additional) -> HTTPResponse:
    """
    generates a json error api response
    :param error: the error code, a value of APIError
    :param description: the error description for the user
    :param status: the HTTP error code
    :return: the created sanic.response.HTTPResponse
    """
    return json_response({
        **additional,
        "error": "err_ " + error[0],
        "description": description
    }, status=error[1])


def json_response(di: Union[dict, list], **kwargs) -> HTTPResponse:
    """
    generates a json response based on a dict
    translates ObjectIds to str
    :return: the created sanic.response.HTTPResponse
    """
    return json(di, dumps=lambda s: json_dumps(s, default=serialize_objectids), **kwargs)


def get_dummy_objid(timestamp: int) -> ObjectId:
    """
    generates a dummy ObjectId
    """
    return ObjectId(("%8x" % timestamp) + ("0" * 16))


def serialize_objectids(v):
    """
    stringifies ObjectIds
    function to be passed to json.dumps as default
    """
    # translate ObjectIds
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, set):
        return list(v)
    raise ValueError("value can't be serialized: " + str(v))


def get_path(url) -> Tuple[Union[bytes, str], Union[bytes, str]]:
    """
    extracts and splits the path of a url
    """
    return split_path(urlparse(url).path)


async def download_and_save(url: str, path: str) -> bool:
    """
    downloads a file and saves it to the given path
    :param url: the url to download
    :param path: the path of the output file
    :return: True, if the file was saved successfully
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                f = await aiofiles.open(path, mode='wb')
                await f.write(await resp.read())
                await f.close()
                return True
    raise FileNotFoundError("file couldn't be saved")


def server_endpoint():
    """
    marks an api endpoint as a server endpoint
    needs <i> parameter in path
    fetches the server for the id and saves it to request.ctx.server for access in the endpoint
    raises json error and cancels response when server couldn't be found
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(req: Request, *args, **kwargs) -> HTTPResponse:
            if "i" not in kwargs.keys():
                return json_error(APIError.MISSING_VALUE, "please specify the server id in the uri")
            i = kwargs["i"]
            server = await Config.SEMOXY_INSTANCE.server_manager.get_server(i)
            if server is None:
                return json_error(APIError.INVALID_SERVER, "no server was found for your id")

            req.ctx.server = server
            return await f(req, *args, **kwargs)
        return decorated_function
    return decorator


def requires_server_online(online: bool = True):
    """
    decorator for a @server_endpoint()
    raises json error when the server from the @server_endpoint() hasn't the running state that is specified
    :param online: whether the server has to be online or offline for the request to pass to the handler
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(req: Request, *args, **kwargs) -> HTTPResponse:
            if online != req.ctx.server.running:
                return json_error(APIError.INVALID_SERVER_STATUS, f"this endpoint requires the server to be {'online' if online else 'offline'}")
            return await f(req, *args, **kwargs)
        return decorated_function
    return decorator


def bind_model(model: Type[pydantic.BaseModel]):
    def decorator(f):
        @wraps(f)
        async def decorated_function(req: Request, *args, **kwargs) -> HTTPResponse:
            try:
                data = model(**req.json)
            except pydantic.ValidationError as e:
                return json_error(APIError.INVALID_PAYLOAD_SCHEMA, "invalid payload type", errors=e.errors())
            return await f(req, data, *args, **kwargs)
        return decorated_function
    return decorator


def requires_post_params(*json_keys: str):
    """
    rejects post requests if they have not the specified json keys in it
    :param json_keys: the json keys that the request has to have for the handler to call
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(req: Request, *args, **kwargs) -> HTTPResponse:
            for prop in json_keys:
                if prop not in req.json.keys():
                    return json_error(APIError.MISSING_VALUE, f"you need to specify {prop}", field=prop)
            return await f(req, *args, **kwargs)
        return decorated_function
    return decorator


def requires_login(logged_in: bool = True):
    """
    requires the user to be logged in to access this endpoint
    :param logged_in: whether the user has to be logged in or has to be not logged in
    """
    def decorator(f):
        @wraps(f)
        async def decorated_function(req: Request, *args, **kwargs) -> HTTPResponse:
            if logged_in and not req.ctx.user:
                return json_error(APIError.UNAUTHENTICATED, "you need to be logged in to access this endpoint")
            if not logged_in and req.ctx.user:
                return json_error(APIError.NO_PERMISSION, "you can't use this endpoint while logged in")
            return await f(req, *args, **kwargs)
        return decorated_function
    return decorator


def renew_root_creation_token() -> None:
    """
    renews the root account creation secret in root.txt
    """
    print("regenerating root user creation secret")
    with open("root.txt", "w") as f:
        f.write(secrets.token_urlsafe(48))


def get_root_creation_token() -> str:
    """
    reads the root account creation secret in root.txt
    :return: the current root creation secret
    """
    with open("root.txt", "r") as f:
        return f.read()


async def get_public_ip() -> str:
    """
    fetches the public ip of this semoxy server
    :return: the public ip or domain name of this semoxy server
    """
    if Config.STATIC_IP:
        ip = Config.STATIC_IP
    else:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.ipify.org/") as resp:
                ip = await resp.text()
    if not Regexes.IP.match(ip):
        ip = socket.gethostbyname(ip)
    return ip
