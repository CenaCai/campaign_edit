"""API v1 聚合路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import create_token, get_current_user
from ...models import Project, User
from ...schemas import LoginIn, ProjectIn, ProjectOut, TokenOut, UserOut

from . import contents, intents, plugins, system

api_router = APIRouter()

auth_router = APIRouter(prefix="/auth", tags=["auth"])
project_router = APIRouter(prefix="/projects", tags=["projects"])


@auth_router.post("/login", response_model=TokenOut, summary="登录")
def login(req: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    from ...deps import verify_password
    u = db.execute(select(User).where(User.email == req.email)).scalar_one_or_none()
    if u is None or not verify_password(req.password, u.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    token, ttl = create_token(u.id)
    return TokenOut(access_token=token, expires_in=ttl,
                    user=UserOut.model_validate(u))


@auth_router.get("/me", response_model=UserOut, summary="当前用户")
def me(user: User = Depends(get_current_user)) -> User:
    return user


@auth_router.post("/register", response_model=TokenOut, summary="注册（首个注册者为 admin）")
def register(req: LoginIn, db: Session = Depends(get_db),
             name: str = "") -> TokenOut:
    from ...deps import hash_password
    exists = db.execute(select(User)).scalars().first()
    if exists is not None:
        raise HTTPException(409, "系统已初始化，请用登录接口")
    u = User(email=req.email, name=name or req.email.split("@")[0], role="admin",
             password_hash=hash_password(req.password))
    db.add(u)
    db.commit()
    db.refresh(u)
    token, ttl = create_token(u.id)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(u))


@project_router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.key)).scalars())


@project_router.post("", response_model=ProjectOut)
def create_project(req: ProjectIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> Project:
    if db.execute(select(Project).where(Project.key == req.key)).scalar_one_or_none():
        raise HTTPException(409, f"项目 key 已存在: {req.key}")
    p = Project(**req.model_dump(), created_by=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


api_router.include_router(auth_router)
api_router.include_router(project_router)
api_router.include_router(system.router)
api_router.include_router(intents.router)
api_router.include_router(contents.router)
api_router.include_router(contents.tpl_router)
api_router.include_router(contents.theme_router)
api_router.include_router(plugins.router)
api_router.include_router(plugins.block_router)