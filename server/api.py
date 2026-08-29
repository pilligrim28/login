#!/usr/bin/env python3
"""REST API для серверной версии."""

import sys
import os
import threading
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from contextlib import asynccontextmanager

from core.config import Config
from core.logger import log
from core.database import Database
from core.sms import SMSActivate
from workers.worker import Worker

app = FastAPI(title="MassReg Server API", version="0.1.0")

config = None
db = None
worker = None
worker_thread = None
worker_status = {"running": False, "done": 0, "total": 0, "success": 0, "failed": 0}


class RegistrationRequest(BaseModel):
    total: int = 100
    threads: int = 10


class SMSConfig(BaseModel):
    api_key: str
    service_code: str = "op"


@app.on_event("startup")
async def startup():
    global config, db
    try:
        config = Config("config.yaml")
    except FileNotFoundError:
        import yaml
        default = {
            "sms": {"api_key": "", "service_code": "op", "country": 0},
            "proxy": {"enabled": False, "type": "http", "proxies": [], "rotation_url": ""},
            "worker": {"threads": 5, "total_registrations": 50, "headless": True},
            "database": {"type": "sqlite", "sqlite_path": "accounts.db"}
        }
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(default, f, default_flow_style=False, allow_unicode=True)
        config = Config("config.yaml")

    db = Database(config)
    log.info("Server API started")


@app.get("/")
async def root():
    return {"status": "ok", "service": "MassReg Server", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy", "worker_running": worker_status["running"]}


@app.get("/balance")
async def get_balance():
    api_key = config.get("sms.api_key", "")
    if not api_key:
        raise HTTPException(400, "API-ключ не настроен")
    sms = SMSActivate(api_key)
    balance = sms.get_balance()
    if balance is None:
        raise HTTPException(500, "Ошибка получения баланса")
    return {"balance": balance}


@app.post("/config/sms")
async def set_sms_config(sms_conf: SMSConfig):
    config.set("sms.api_key", sms_conf.api_key)
    config.set("sms.service_code", sms_conf.service_code)
    config.save()
    return {"status": "ok"}


@app.get("/stats")
async def get_stats():
    return db.get_stats()


@app.post("/start")
async def start_registration(req: RegistrationRequest):
    global worker, worker_thread, worker_status

    if worker_status["running"]:
        raise HTTPException(400, "Регистрация уже запущена")

    config.set("worker.total_registrations", req.total)
    config.set("worker.threads", req.threads)
    config.save()

    worker = Worker(config)
    worker_status = {"running": True, "done": 0, "total": req.total,
                     "success": 0, "failed": 0}

    def on_progress(done, total, success, failed):
        worker_status["done"] = done
        worker_status["total"] = total
        worker_status["success"] = success
        worker_status["failed"] = failed

    def on_finished():
        worker_status["running"] = False

    worker.on_progress = on_progress
    worker.on_finished = on_finished

    worker_thread = threading.Thread(target=worker.run, daemon=True)
    worker_thread.start()

    return {"status": "started", "total": req.total, "threads": req.threads}


@app.post("/stop")
async def stop_registration():
    global worker, worker_status

    if not worker_status["running"]:
        raise HTTPException(400, "Регистрация не запущена")

    worker.stop()
    worker_status["running"] = False
    return {"status": "stopping"}


@app.get("/progress")
async def get_progress():
    return worker_status


@app.get("/accounts")
async def get_accounts(limit: int = 100, offset: int = 0):
    accounts = db.get_all_accounts()
    return accounts[offset:offset + limit]