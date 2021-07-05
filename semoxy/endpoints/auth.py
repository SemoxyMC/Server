import secrets

from sanic.blueprints import Blueprint
from sanic.request import Request

from ..models import User
from ..models import WebsocketTicket
from ..util import json_res, requires_post_params, requires_login

account_blueprint = Blueprint("account", url_prefix="account")


@account_blueprint.post("/login")
@requires_login(False)
@requires_post_params("username", "password")
async def login_post(req):
    """
    post endpoint for logging in a user
    """
    user = await User.fetch_by_name(req.json["username"])
    if user:
        if await user.check_password(str(req.json["password"])):
            session = await user.create_session()
            return json_res({"success": "logged in successfully", "data": {"sessionId": session.sid}})
    return json_res({"error": "Wrong Credentials", "status": 401, "description": "either username or password are wrong"}, status=401)


@account_blueprint.get("/login")
async def login_get(req):
    """
    endpoint to redirect on wrong login
    """
    if not req.ctx.session:
        return json_res({"error": "Not Logged In", "status": 401, "description": "please login using POST to /account/login"}, status=401)
    else:
        return json_res({"info": "you are already logged in", "status": 200})


@account_blueprint.get("/session")
async def check_session(req):
    """
    returns information about a users session
    """
    out = {"loggedIn": req.ctx.session is not None}
    if req.ctx.session:
        out["expiration"] = req.ctx.session.expiration
        out["userId"] = req.ctx.session.userId
    return json_res(out)


@account_blueprint.get("/logout")
@requires_login()
async def logout(req):
    """
    get endpoint for logging out a user
    """
    await req.ctx.session.logout()
    return json_res({"success": "logged out successfully", "data": {}})


@account_blueprint.get("/")
@requires_login()
async def fetch_me(req):
    """
    sends information about the current user to the client
    """
    return json_res({"username": req.ctx.user.name, "permissions": req.ctx.user.permissions})


@account_blueprint.get("/ticket")
@requires_login()
async def open_ticket(req: Request):
    ticket: WebsocketTicket = await req.ctx.user.create_ticket(req.ip, req.headers["User-Agent"] or "unknown agent")
    return json_res({"success": "ticket created", "data": {"token": ticket.token}})


async def get_new_ticket(db):
    ticket = secrets.token_urlsafe(24)
    while await db["wsticket"].find_one({"ticket": ticket}):
        ticket = secrets.token_urlsafe(24)
    return ticket
